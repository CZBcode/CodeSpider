import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from agent_client.executor import ExecutionError
from backend.models import Event, Task, new_id, now_iso
from memory.service import MemoryService
from backend.model_gateway import ModelGateway
from backend.tool_protocol import ToolRequest


class TaskManager:
    TOOL_RETRIES = 2

    def __init__(self, store: Any, workspaces: Any, model: Optional[ModelGateway] = None, tools: Any = None):
        self.store = store
        self.workspaces = workspaces
        self.tools = tools
        self.memory = getattr(tools, "memory", None) or MemoryService(store)
        self.model = model or ModelGateway()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="codespider-task")
        self._lock = threading.RLock()
        self._cancelled = set()

    def _tasks(self) -> List[Dict[str, Any]]:
        return self.store.read("tasks", [])

    def _save_task(self, task: Task) -> None:
        self.store.update("tasks", [], lambda items: [item for item in items if item["id"] != task.id] + [task.to_dict()])

    def _emit(self, task_id: str, event_type: str, payload: Dict[str, Any]) -> Event:
        with self._lock:
            events = self.store.read("events", [])
            sequence = max([item["sequence"] for item in events if item["task_id"] == task_id] or [0]) + 1
            event = Event(new_id("evt"), task_id, sequence, event_type, payload)
            events.append(event.to_dict())
            self.store.write("events", events)
            return event

    def get(self, task_id: str) -> Task:
        for item in self._tasks():
            if item["id"] == task_id:
                return Task(**item)
        raise KeyError("task not found")

    def events(self, task_id: str, after: int = 0) -> List[Event]:
        return [Event(**item) for item in self.store.read("events", []) if item["task_id"] == task_id and item["sequence"] > after]

    def create(self, workspace_id: str, goal: str, patches: Optional[List[Dict[str, Any]]] = None, model_id: str = "", on_model_call: Any = None, model_settings: Optional[Dict[str, Any]] = None, context_approved: bool = False, owner_id: str = "", on_generation_start: Any = None) -> Task:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal cannot be empty")
        workspace = self.workspaces.get(workspace_id)
        if type(context_approved) is not bool:
            raise ValueError("context_approved must be a boolean")
        config = model_settings if model_settings is not None else self.model.config()
        remote = config.get("provider") not in ("local", "", None) and bool(config.get("base_url"))
        context = {"project_type": workspace.project_type}
        if remote and not patches:
            from backend.policy import ApprovalRequired
            if workspace.execution_mode == "safe" and not context_approved:
                raise ApprovalRequired("generation_context", "生成代码需要读取工程源码与符号并发送给所选模型，请确认", "confirm")
            response = self.tools.call(ToolRequest("code", "context", {"goal": goal}, workspace_id=workspace.id,
                approval={"approved": context_approved}))
            if not response.ok:
                raise ValueError((response.error or {}).get("message", "cannot read generation context"))
            context.update(response.data, require_patches=True)
        conversation_turn_id = on_generation_start() if on_generation_start else ""
        turn = self._make_turn(workspace, goal, model_settings, context)
        if self.workspaces.get(workspace_id).to_dict() != workspace.to_dict():
            raise ValueError("工程设置已改变，请重新生成补丁")
        if on_model_call:
            on_model_call()
        task = Task(new_id("task"), workspace_id, goal.strip(), plan=turn["steps"], patches=patches or turn.get("patches", []), thinking=turn["thinking"], tool_calls=turn.get("tool_calls", []), response_schema=turn.get("schema", "agent.turn/v1"), model_id=model_id)
        task.design = turn.get("design", {})
        task.summary = turn["summary"]
        task.owner_id = owner_id
        task.conversation_turn_id = conversation_turn_id
        task.design_contract = context.get("design_contract", {})
        task.design_review = turn.get("design_review", {})
        task.workspace_snapshot = workspace.to_dict()
        self._save_task(task)
        self._emit(task.id, "task.created", {"goal": task.goal})
        self._emit(task.id, "task.plan_ready", {"schema": task.response_schema, "summary": task.summary, "thinking": task.thinking, "steps": task.plan, "tool_calls": task.tool_calls})
        return task

    def _make_turn(self, workspace: Any, goal: str, model_settings: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        generated = self.model.validate_turn(self.model.plan(goal, context or {"project_type": workspace.project_type}, settings_override=model_settings))
        if context and context.get("require_patches"):
            ModelGateway.validate_generation(generated, context)
        return generated

    def approve(self, task_id: str) -> Task:
        with self._lock:
            task = self.get(task_id)
            if task.status not in ("created", "waiting_approval"):
                raise ValueError("task is not awaiting approval")
            # Legacy pending tasks acquire their snapshot once, at approval.
            if not task.workspace_snapshot:
                task.workspace_snapshot = self.workspaces.get(task.workspace_id).to_dict()
            task.status = "executing"
            task.updated_at = now_iso()
            self._save_task(task)
            self._emit(task.id, "approval.accepted", {})
            self.executor.submit(self._run, task.id)
            return task

    def cancel(self, task_id: str) -> Task:
        with self._lock:
            task = self.get(task_id)
            if task.status == "cancelled":
                return task
            if task.status in ("succeeded", "failed"):
                raise ValueError("completed task cannot be cancelled")
            needs_agent = task.status in ("executing", "cancelling")
            self._cancelled.add(task_id)
            task.status = "cancelling"
            task.updated_at = now_iso()
            self._save_task(task)
            self._emit(task.id, "task.cancel_requested", {})
        if needs_agent:
            request = ToolRequest(tool="process", action="cancel", task_id=task_id, workspace_id=task.workspace_id)
            self._emit(task_id, "tool.call", {"request": request.to_dict(), "collapsed": True})
            response = self.tools.call(request)
            self._emit(task_id, "tool.result", response.to_dict())
            if not response.ok:
                # Keep cancelling so the caller can retry; never claim the
                # Agent stopped a command without its acknowledgement.
                raise ValueError((response.error or {}).get("message", "Agent cancellation failed"))
        with self._lock:
            task = self.get(task_id)
            if task.status != "cancelled":
                task.status = "cancelled"
                task.updated_at = now_iso()
                self._save_task(task)
                self._emit(task.id, "task.cancelled", {})
            return task

    def _run(self, task_id: str) -> None:
        task = self.get(task_id)
        try:
            workspace = self.workspaces.get(task.workspace_id, task.id)
            self._emit(task_id, "thinking.started", {"label": "思考中", "thinking": task.thinking, "collapsed": True})
            index_response = self._call_tool(task_id, ToolRequest(tool="code", action="index", workspace_id=task.workspace_id, task_id=task_id, approval={"approved": True, "source": "task_approval"}))
            self._emit(task_id, "index.updated", index_response.data)
            if task_id in self._cancelled:
                return
            if task.patches:
                self._review_design(task, proposed=True)
                for patch in task.patches:
                    operation = patch.get("operation", "apply_patch" if "expected" in patch else "write_file")
                    if operation == "apply_patch":
                        request = ToolRequest(tool="workspace", action="apply_patch", workspace_id=task.workspace_id, task_id=task_id, arguments={"path": patch.get("path", ""), "expected": patch.get("expected", ""), "replacement": patch.get("replacement", "")}, approval={"approved": True, "source": "task_approval"})
                    else:
                        request = ToolRequest(tool="workspace", action="create_file" if operation == "create" else "write_file", workspace_id=task.workspace_id, task_id=task_id, arguments={"path": patch.get("path", ""), "content": patch.get("replacement", patch.get("content", ""))}, approval={"approved": True, "source": "task_approval"})
                    result = self._call_tool(task_id, request)
                    self._emit(task_id, "file.changed", result.data)
                index_response = self._call_tool(task_id, ToolRequest(tool="code", action="index", workspace_id=task.workspace_id,
                    task_id=task_id, approval={"approved": True, "source": "task_approval"}))
                self._emit(task_id, "index.updated", index_response.data)
            else:
                model_config = self.model.config()
                self._emit(task_id, "agent.notice", {"message": "MVP 执行器已完成工程分析。真实模型接入后，将在此处根据目标生成补丁。", "model": "%s/%s" % (model_config.get("provider"), model_config.get("model"))})
            detection = self._call_tool(task_id, ToolRequest(tool="code", action="detect", workspace_id=task.workspace_id,
                task_id=task_id, approval={"approved": True, "source": "task_approval"}))
            project_type = detection.data["project_type"]
            self._emit(task_id, "project.detected", detection.data)
            verify_command = self._default_verify(project_type)
            if task.patches and not verify_command:
                raise ExecutionError("无法识别生成代码的工程类型，未执行验证；请补充工程配置后重新验证")
            commands = detection.data.get("setup_commands", []) + ([verify_command] if verify_command else []) + detection.data.get("verification_commands", [])
            for command in dict.fromkeys(commands):
                timeout = 300 if command in detection.data.get("setup_commands", []) else 180
                request = ToolRequest(tool="process", action="run", workspace_id=task.workspace_id, task_id=task_id, arguments={"command": command, "timeout": timeout}, approval={"approved": True, "source": "task_approval"})
                result = self._call_tool(task_id, request)
                self._emit(task_id, "process.output", dict(result.data, command=command))
                if result.data.get("exit_code") != 0:
                    raise ExecutionError(self._friendly_process_failure(command, result.data))
                if "unittest discover" in command and "Ran 0 tests" in result.data.get("output", ""):
                    raise ExecutionError("发现测试目录但没有执行任何 unittest 测试，请检查测试框架和发现配置")
            if task.patches:
                self._review_design(task)
            self._emit(task_id, "verification.completed", {"commands": list(dict.fromkeys(commands))})
            completion_message = "文件修改已完成，验证命令通过。" if task.patches else "分析与验证已完成，未修改文件。"
            if commands == ["python3 -m compileall -q ."]:
                completion_message += "仅检查了 Python 语法，未发现可执行测试。"
            with self._lock:
                if task_id in self._cancelled:
                    return
                self.memory.add_short_term(task_id, {"goal": task.goal, "status": "succeeded"})
                task.status = "succeeded"
                task.updated_at = now_iso()
                self._save_task(task)
                self._emit(task_id, "task.succeeded", {"message": completion_message})
        except Exception as exc:
            with self._lock:
                if task_id in self._cancelled:
                    return
                raw_error = str(exc)
                friendly_error = self._friendly_error(raw_error)
                task.status = "failed"
                task.error = friendly_error
                task.updated_at = now_iso()
                self._save_task(task)
                self._emit(task_id, "task.failed", {"error": friendly_error, "details": raw_error if raw_error != friendly_error else ""})

    def _review_design(self, task, proposed=False):
        result = self._call_tool(task.id, ToolRequest("code", "design_review",
            {"patches": task.patches if proposed else [], "design": task.design or None,
             "design_contract": task.design_contract, "check_design": bool(task.design_contract)},
            workspace_id=task.workspace_id, task_id=task.id,
            approval={"approved": True, "source": "task_approval"}))
        task.design_review = result.data
        self._emit(task.id, "design.reviewed", dict(result.data, phase="before_write" if proposed else "after_tests"))
        if result.data.get("blocking"):
            raise ExecutionError("Design contract failed; see structure review findings")

    def _call_tool(self, task_id: str, request: ToolRequest):
        if self.tools is None:
            raise RuntimeError("tool service is not configured")
        max_attempts = self.TOOL_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            with self._lock:
                if task_id in self._cancelled:
                    raise ExecutionError("task cancelled")
                self._emit(task_id, "tool.call", {"request": request.to_dict(), "collapsed": True,
                    "attempt": attempt, "max_attempts": max_attempts})
            response = self.tools.call(request)
            self._emit(task_id, "tool.result", response.to_dict())
            process_failed = request.tool == "process" and request.action == "run" and response.ok and response.data.get("exit_code") != 0
            error = response.error or {}
            retryable = (self._retryable_process_result(response.data) if process_failed else bool(error.get("retryable")))
            if response.ok and not process_failed:
                if attempt > 1:
                    response.data["attempts"] = attempt
                return response
            if attempt >= max_attempts or not retryable:
                if response.ok:
                    response.data["attempts"] = attempt
                    return response
                message = error.get("message", "工具调用失败")
                raise ValueError(message)
            self._emit(task_id, "tool.retry", {"collapsed": True, "attempt": attempt + 1,
                "max_attempts": max_attempts, "message": "工具调用失败，正在自动重试（第 %s/%s 次）" % (attempt + 1, max_attempts),
                "details": error.get("message", "命令退出码非 0") if error else "命令退出码非 0"})
            time.sleep(min(0.25 * attempt, 0.75))
        raise RuntimeError("tool retry loop exhausted")

    @staticmethod
    def _friendly_process_failure(command: str, result: Dict[str, Any]) -> str:
        exit_code = result.get("exit_code")
        output = str(result.get("output", ""))
        if command.strip().split(" ", 1)[0] in ("mvn", "mvnw", "./mvnw") and (
            exit_code == 127 or "找不到 Maven" in output or "command not found" in output.lower()
        ):
            return "执行失败（exit code %s）：当前 Agent 环境找不到 Maven。请安装 Maven 3.8+ 或提供 ./mvnw，然后重试。" % exit_code
        return "执行失败（exit code %s）：命令 %s 未通过。详细输出已折叠，请展开查看，修复后重试。" % (exit_code, command)

    @staticmethod
    def _retryable_process_result(result: Dict[str, Any]) -> bool:
        """Retry only failures that can plausibly succeed without code changes."""
        output = str(result.get("output", "")).lower()
        exit_code = result.get("exit_code")
        transient_markers = (
            "timed out", "timeout", "connection reset", "connection refused",
            "could not transfer artifact", "temporary failure", "503", "502", "429",
        )
        return exit_code in (75, 408, 429, 500, 502, 503, 504) or any(marker in output for marker in transient_markers)

    @staticmethod
    def _friendly_error(message: str) -> str:
        if "找不到 Maven" in message:
            return message
        if "file not found" in message.lower() or "no such file" in message.lower():
            return "执行失败：运行环境缺少所需命令或文件。详细错误已折叠，请检查工程配置后重试。"
        return message

    @staticmethod
    def _default_verify(project_type: str) -> Optional[str]:
        return {"python": "python3 -m compileall -q .", "java-springboot": "mvn -q test", "vue": "npm run build"}.get(project_type)
