from typing import Any, Dict
import threading
from pathlib import PurePosixPath
import re
import hashlib

from agent_client.executor import AgentExecutor, ExecutionError
from agent_client.processes import ProcessManager
from backend.documents import generate_workspace_document
from backend.policy import ApprovalRequired, PolicyError
from backend.tool_protocol import ToolRequest, ToolResponse
from code_intelligence.indexer import CodeIndexer
from code_intelligence.design_contract import CONTRACT_FILE, load_contract, review_proposal
from code_intelligence.structure import SOURCE_SUFFIXES, review_structure, summarize_structure
from fnmatch import fnmatch
from memory.service import MemoryService


class ToolService:
    """Dispatches all Agent capabilities through the versioned tool protocol."""

    def __init__(self, store: Any, workspaces: Any, processes: ProcessManager):
        self.store = store
        self.workspaces = workspaces
        self.processes = processes
        self.memory = MemoryService(store)
        self._control_lock = threading.Lock()
        self._task_controls = {}

    def _control(self, task_id):
        with self._control_lock:
            return self._task_controls.setdefault(task_id, (threading.RLock(), threading.Event()))

    def call(self, payload: Dict[str, Any]) -> ToolResponse:
        try:
            request = payload if isinstance(payload, ToolRequest) else ToolRequest.from_dict(payload)
            # Validate even actions that do not otherwise inspect approval.
            request.approved
            if request.tool == "process" and request.action == "cancel":
                if not request.task_id:
                    raise ValueError("task_id is required for cancellation")
                lock, cancelled = self._control(request.task_id)
                cancelled.set()
                # Acknowledge only after the in-flight operation has finished
                # (commands observe the event and kill/reap their process group).
                with lock:
                    data = {"task_id": request.task_id, "cancelled": True}
            elif request.task_id:
                lock, cancelled = self._control(request.task_id)
                with lock:
                    if cancelled.is_set():
                        raise ExecutionError("task cancelled")
                    data = self._dispatch(request, cancelled)
            else:
                data = self._dispatch(request)
            return ToolResponse(request_id=request.request_id, ok=True, data=data)
        except ApprovalRequired as exc:
            request_id = payload.request_id if isinstance(payload, ToolRequest) else str(payload.get("request_id", ""))
            return ToolResponse(request_id=request_id, ok=False, error={"code": "APPROVAL_REQUIRED", "message": exc.reason, "approval_required": True, "risk": exc.risk, "operation": exc.operation, "retryable": False})
        except (KeyError, ValueError, PolicyError, ExecutionError, OSError) as exc:
            request_id = payload.request_id if isinstance(payload, ToolRequest) else str(payload.get("request_id", ""))
            message = str(exc)
            retryable = self._retryable_error(exc)
            return ToolResponse(request_id=request_id, ok=False, error={"code": "TOOL_ERROR", "message": message, "retryable": retryable})

    @staticmethod
    def _retryable_error(exc: Exception) -> bool:
        if isinstance(exc, OSError):
            return not isinstance(exc, FileNotFoundError)
        if not isinstance(exc, ExecutionError):
            return False
        message = str(exc).lower()
        # These errors describe a stable user or workspace problem. Retrying
        # would repeat the same operation and could hide the real fix.
        stable = ("cancelled", "file changed", "source changed", "not found", "找不到", "larger than", "requires")
        return not any(marker in message for marker in stable)

    def catalog(self) -> Dict[str, Any]:
        return {
            "api_version": "1.0",
            "tools": [
                {"tool": "workspace", "actions": ["list_tree", "read_file", "search", "write_file", "create_file", "apply_patch"]},
                {"tool": "code", "actions": ["index", "symbols", "detect", "context", "design_review"]},
                {"tool": "process", "actions": ["run", "start", "list", "stop", "cancel"]},
                {"tool": "memory", "actions": ["search", "project", "preference", "skill"]},
                {"tool": "document", "actions": ["generate"]},
            ],
        }

    def _dispatch(self, request: ToolRequest, cancel_event=None) -> Dict[str, Any]:
        if request.tool == "workspace":
            return self._workspace(request)
        if request.tool == "code":
            return self._code(request)
        if request.tool == "process":
            return self._process(request, cancel_event)
        if request.tool == "memory":
            return self._memory(request)
        if request.tool == "document":
            workspace = self.workspaces.get(request.workspace_id, request.task_id)
            if request.action != "generate":
                raise ValueError("unsupported document action")
            if self.workspaces.policy(request.workspace_id, request.task_id).mode == "safe" and not request.approved:
                raise ApprovalRequired("document_generate", "安全执行模式要求确认读取工程并生成文档", "confirm")
            return generate_workspace_document(workspace, request.arguments.get("title", "工程说明"))
        raise ValueError("unknown tool: %s" % request.tool)

    def _workspace(self, request: ToolRequest) -> Dict[str, Any]:
        executor = AgentExecutor(self.workspaces.policy(request.workspace_id, request.task_id))
        if request.action == "list_tree":
            return {"items": self.workspaces.tree(request.workspace_id, int(request.arguments.get("limit", 1000)), request.task_id)}
        if request.action == "read_file":
            return {"path": request.arguments["path"], "content": executor.read_file(request.arguments["path"], approved=request.approved)}
        if request.action == "search":
            return {"items": executor.search(request.arguments.get("query", ""), int(request.arguments.get("limit", 100)), approved=request.approved)}
        if request.action == "write_file":
            return executor.write_file(request.arguments["path"], request.arguments.get("content", ""), approved=request.approved)
        if request.action == "create_file":
            return executor.create_file(request.arguments["path"], request.arguments.get("content", ""), approved=request.approved)
        if request.action == "apply_patch":
            return executor.apply_patch(request.arguments["path"], request.arguments.get("expected", ""), request.arguments.get("replacement", ""), approved=request.approved)
        raise ValueError("unsupported workspace action")

    def _code(self, request: ToolRequest) -> Dict[str, Any]:
        workspace = self.workspaces.get(request.workspace_id, request.task_id)
        if self.workspaces.policy(request.workspace_id, request.task_id).mode == "safe" and not request.approved:
            raise ApprovalRequired("code_intelligence", "安全执行模式要求确认分析工程代码", "confirm")
        if request.action == "detect":
            from code_intelligence.adapters import detect_project
            detected = detect_project(workspace.root)
            self.workspaces.refresh_type(request.workspace_id, request.task_id)
            return {"project_type": detected["type"], "verification_commands": detected.get("verification_commands", []),
                    "setup_commands": detected.get("setup_commands", [])}
        if request.action == "design_review":
            context = self._context(request, workspace, review=True)
            expected = request.arguments.get("design_contract")
            if expected and expected != context["design_contract"]:
                raise ValueError("Design contract changed; regenerate the task")
            patches = request.arguments.get("patches", [])
            if patches:
                from backend.patch_contract import PatchContract
                normalized = PatchContract._patches(patches)
                if len({p['path'] for p in normalized}) != len(normalized):
                    raise ValueError("Duplicate patch paths are not allowed")
                for patch in normalized:
                    PatchContract._validate_patch(patch)
                    if "base_sha256" in patch:
                        content = context["files"].get(patch["path"])
                        if content is None or hashlib.sha256(content.encode("utf-8")).hexdigest() != patch["base_sha256"]:
                            raise ValueError("Source hash changed; regenerate: " + patch["path"])
                        if "expected" not in patch: patch["expected"] = content
                    if patch["operation"] == "apply_patch" and context["files"].get(patch["path"]) != patch.get("expected"):
                        raise ValueError("Source changed; regenerate: " + patch["path"])
                return review_proposal(context, normalized, request.arguments.get("design"),
                                       check_design=bool(request.arguments.get("check_design")), raise_on_block=False)
            return review_structure(context["files"], context["design_contract"], context["structure_incomplete"])
        if request.action == "context":
            return self._context(request, workspace)
        if request.action == "index":
            symbols = CodeIndexer(workspace.root, self.workspaces.policy(request.workspace_id, request.task_id)).build()
            return {"symbols": len(symbols), "project_type": workspace.project_type}
        if request.action == "symbols":
            return {"items": self.workspaces.symbols(request.workspace_id, request.task_id)}
        raise ValueError("unsupported code action")

    def _context(self, request, workspace, review=False):
        policy = self.workspaces.policy(request.workspace_id, request.task_id)
        executor = AgentExecutor(policy)
        paths = [item["path"] for item in self.workspaces.tree(workspace.id, 1000, request.task_id)]
        terms = set(re.findall(r"[a-zA-Z_][\w.]+", request.arguments.get("goal", "").lower()))
        def allowed(path):
            p = PurePosixPath(path)
            if any(part.startswith(".") for part in p.parts):
                return False
            if any(word in p.name.lower() for word in ("secret", "credential", "token", "password")):
                return False
            return p.suffix in (".py", ".java", ".vue", ".js", ".ts", ".json", ".xml", ".toml", ".md", ".html", ".css") or p.name == "requirements.txt"
        candidates = sorted((p for p in paths if allowed(p)), key=lambda p: (p != CONTRACT_FILE, -sum(t in p.lower() for t in terms), p))
        files, skipped, budget = {}, [], (512_000 if review else 96_000)
        for path in candidates:
            if len(files) >= (120 if review else 24):
                skipped.append(path)
                continue
            try:
                content = executor.read_file(path, max_bytes=min(64_000, budget), approved=request.approved)
            except (ExecutionError, OSError, UnicodeError, PolicyError):
                skipped.append(path)
                continue
            files[path] = content
            budget -= len(content.encode("utf-8"))
        if CONTRACT_FILE in paths and CONTRACT_FILE not in files:
            raise ValueError("Cannot read design-contract.json within source budget")
        contract = load_contract(files)
        structure_incomplete = len(paths) >= 1000 or any(
            p.endswith(SOURCE_SUFFIXES) and not any(fnmatch(p, pattern) for pattern in contract["exclude"])
            for p in paths if p not in files)
        # Index only the selected context files; do not send unrelated symbols.
        indexer = CodeIndexer(workspace.root, policy)
        symbols = []
        for path in files:
            if path.endswith(".py"):
                symbols.extend(indexer._python(path, path))
            elif path.endswith((".java", ".vue", ".ts", ".js")):
                symbols.extend(indexer._regex(path, path, "java" if path.endswith(".java") else "vue"))
        return {"project_type": workspace.project_type, "description": workspace.description,
                "files": files, "file_paths": paths, "symbols": symbols[:120], "skipped_files": skipped,
                "file_hashes": {path: hashlib.sha256(content.encode("utf-8")).hexdigest() for path, content in files.items()},
                "context_limited": bool(skipped) or len(paths) >= 1000,
                "design_contract": contract, "structure_incomplete": structure_incomplete,
                "structure": summarize_structure(review_structure(files, contract, structure_incomplete)) if not review else {}}

    def _process(self, request: ToolRequest, cancel_event=None) -> Dict[str, Any]:
        if request.action == "stop":
            pid = int(request.arguments["pid"])
            if request.workspace_id:
                workspace = self.workspaces.get(request.workspace_id, request.task_id)
                if pid not in [item["pid"] for item in self.processes.list(workspace.root)]:
                    raise ValueError("process does not belong to workspace")
            return self.processes.stop(pid)
        workspace = self.workspaces.get(request.workspace_id, request.task_id)
        if request.action == "run":
            return AgentExecutor(self.workspaces.policy(request.workspace_id, request.task_id)).run_command(request.arguments["command"], int(request.arguments.get("timeout", 60)), approved=request.approved, cancel_event=cancel_event)
        if request.action == "start":
            return self.processes.start(self.workspaces.policy(request.workspace_id, request.task_id), request.arguments["command"], approved=request.approved)
        if request.action == "list":
            return {"items": self.processes.list(workspace.root)}
        raise ValueError("unsupported process action")

    def _memory(self, request: ToolRequest) -> Dict[str, Any]:
        scope_id = request.arguments.get("scope_id", request.workspace_id or "global")
        if request.action == "search":
            return {"items": self.memory.search(scope_id, request.arguments.get("query", ""))}
        if request.action == "project":
            return self.memory.add_project(scope_id, request.arguments.get("content", {}))
        if request.action == "preference":
            return self.memory.set_preferences(scope_id, request.arguments.get("content", {}))
        if request.action == "skill":
            return self.memory.add_skill(scope_id, request.arguments.get("name", "未命名 Skill"), request.arguments.get("body", ""), request.arguments.get("trigger", ""))
        raise ValueError("unsupported memory action")
