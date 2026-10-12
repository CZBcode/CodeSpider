import os
from typing import Any, Dict, List, Optional

from backend.models import Workspace, new_id
from backend.policy import WorkspacePolicy
from code_intelligence.adapters import detect_project
from code_intelligence.indexer import CodeIndexer


class WorkspaceManager:
    def __init__(self, store: Any):
        self.store = store

    def list(self) -> List[Workspace]:
        return [Workspace(**item) for item in self.store.read("workspaces", [])]

    def get(self, workspace_id: str, task_id: str = "") -> Workspace:
        if task_id:
            for task in self.store.read("tasks", []):
                if task["id"] == task_id:
                    snapshot = task.get("workspace_snapshot")
                    if task["workspace_id"] != workspace_id or not snapshot or snapshot.get("id") != workspace_id:
                        raise ValueError("task has no matching workspace snapshot; create or approve the task again")
                    return Workspace(**snapshot)
            raise KeyError("task not found")
        for workspace in self.list():
            if workspace.id == workspace_id:
                return workspace
        raise KeyError("workspace not found")

    def create(self, root: str = "", name: Optional[str] = None, start_command: str = "", description: str = "", execution_mode: str = "safe", command_allowlist: Optional[List[str]] = None) -> Workspace:
        if not isinstance(root, str) or (name is not None and not isinstance(name, str)):
            raise ValueError("工程位置和项目名称必须为文本")
        root = root.strip()
        name = (name or "").strip()
        if root:
            real_root = os.path.realpath(os.path.expanduser(root))
        else:
            if not name or name in (".", "..") or any(char in name for char in ("/", "\\", "\0")):
                raise ValueError("使用默认位置时，请填写项目名称，且名称不能包含路径分隔符")
            base = os.path.realpath(os.path.expanduser("~/.codespider/project"))
            real_root = os.path.realpath(os.path.join(base, name))
            if os.path.dirname(real_root) != base:
                raise ValueError("默认项目位置不能指向项目目录之外")
            os.makedirs(real_root, exist_ok=True)
        if not os.path.isdir(real_root):
            raise ValueError("workspace root must be an existing directory")
        detected = detect_project(real_root)
        workspace = Workspace(
            id=new_id("ws"),
            name=name or os.path.basename(real_root) or real_root,
            root=real_root,
            project_type=detected["type"],
            start_command=start_command,
            description=description,
            execution_mode=execution_mode if execution_mode in WorkspacePolicy.MODES else "safe",
            command_allowlist=command_allowlist or [],
        )
        CodeIndexer(real_root, WorkspacePolicy(real_root)).build()
        # Register only a fully initialized workspace. Failed indexing must not
        # leave a record behind, and must never delete an existing user's files.
        self.store.append("workspaces", workspace.to_dict())
        return workspace

    def update(self, workspace_id: str, name: str, root: str, start_command: str, description: str, execution_mode: str = "safe", command_allowlist: Optional[List[str]] = None) -> Workspace:
        workspace = self.get(workspace_id)
        real_root = os.path.realpath(os.path.expanduser(root))
        if not os.path.isdir(real_root):
            raise ValueError("workspace root must be an existing directory")
        if real_root != workspace.root:
            detected = detect_project(real_root)
            workspace.root = real_root
            workspace.project_type = detected["type"]
            CodeIndexer(real_root, WorkspacePolicy(real_root)).build()
        workspace.name = name.strip() or os.path.basename(real_root) or real_root
        workspace.start_command = start_command.strip()
        workspace.description = description.strip()
        workspace.execution_mode = execution_mode if execution_mode in WorkspacePolicy.MODES else "safe"
        workspace.command_allowlist = [item.strip() for item in (command_allowlist or []) if item and item.strip()]
        self.store.update("workspaces", [], lambda items: [item for item in items if item["id"] != workspace_id] + [workspace.to_dict()])
        return workspace

    def refresh_type(self, workspace_id: str, task_id: str = "") -> str:
        workspace = self.get(workspace_id, task_id)
        project_type = detect_project(workspace.root)["type"]
        # A task can still target its original directory after settings change.
        # Never overwrite the new directory's metadata with its result.
        self.store.update("workspaces", [], lambda items: [
            dict(item, project_type=project_type) if item["id"] == workspace_id and item["root"] == workspace.root else item
            for item in items])
        return project_type

    def tree(self, workspace_id: str, limit: int = 1000, task_id: str = "") -> List[Dict[str, Any]]:
        workspace = self.get(workspace_id, task_id)
        policy = WorkspacePolicy(workspace.root)
        result: List[Dict[str, Any]] = []
        for current, dirs, files in os.walk(workspace.root):
            rel_dir = os.path.relpath(current, workspace.root)
            if rel_dir == ".":
                rel_dir = ""
            dirs[:] = [d for d in dirs if not policy.is_ignored(os.path.join(rel_dir, d))]
            for filename in sorted(files):
                relative = os.path.normpath(os.path.join(rel_dir, filename))
                if policy.is_ignored(relative):
                    continue
                result.append({"path": relative, "kind": "file"})
                if len(result) >= limit:
                    return result
        return result

    def policy(self, workspace_id: str, task_id: str = "") -> WorkspacePolicy:
        workspace = self.get(workspace_id, task_id)
        return WorkspacePolicy(workspace.root, mode=workspace.execution_mode, command_allowlist=workspace.command_allowlist)

    def read_file(self, workspace_id: str, relative_path: str, approved: bool = False) -> str:
        workspace = self.get(workspace_id)
        path = self.policy(workspace_id).validate_read(relative_path, approved=approved)
        if not os.path.isfile(path):
            raise FileNotFoundError(relative_path)
        with self.policy(workspace_id).open_file(relative_path) as handle:
            return handle.read()

    def symbols(self, workspace_id: str, task_id: str = "") -> List[Dict[str, Any]]:
        workspace = self.get(workspace_id, task_id)
        policy = self.policy(workspace_id, task_id)
        # External editors and commands can change sources without notifying us.
        return CodeIndexer(workspace.root, policy).build()
