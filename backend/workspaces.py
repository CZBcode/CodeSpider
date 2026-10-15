import os
import re
import fcntl
import hashlib
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from backend.models import Workspace, new_id, now_iso
from backend.policy import WorkspacePolicy
from code_intelligence.adapters import detect_project
from code_intelligence.indexer import CodeIndexer


class WorkspaceManager:
    def __init__(self, store: Any):
        self.store = store

    @contextmanager
    def lease(self, workspace_id, exclusive=False):
        """Coordinate Web generation/approval and Agent operations across processes."""
        if not workspace_id:
            yield
            return
        directory = os.path.join(self.store.root, "workspace-locks")
        os.makedirs(directory, exist_ok=True)
        name = hashlib.sha256(workspace_id.encode()).hexdigest() + ".lock"
        with open(os.path.join(directory, name), "a") as handle:
            try:
                fcntl.flock(handle, (fcntl.LOCK_EX | fcntl.LOCK_NB) if exclusive else fcntl.LOCK_SH)
            except BlockingIOError:
                raise ValueError("项目正在生成或执行操作，请完成后再删除")
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def delete(self, workspace_id, owner_id, confirm_name, confirmed=False):
        """Caller holds the exclusive lease and checks Agent-owned services first."""
        workspace = self.get(workspace_id, owner_id=owner_id)
        if confirmed is not True or confirm_name != workspace.name:
            raise ValueError("请再次确认，并输入完整项目名称")
        if any(t["workspace_id"] == workspace_id and t["status"] in ("executing", "cancelling")
               for t in self.store.read("tasks", [])):
            raise ValueError("项目仍有执行中的任务，请等待完成或取消后再删除")
        if any(j['workspace_id']==workspace_id and j['status'] in ('queued','running') for j in self.store.read('generations',[])):
            raise ValueError("项目仍有排队或生成中的任务，请完成后再删除")
        # Archive first: a failed write leaves the active project usable. Keep
        # roots reserved so deletion never makes another user's files accessible.
        archived = dict(workspace.to_dict(), deleted_at=now_iso())
        self.store.update("deleted_workspaces", [], lambda items:
            [w for w in items if w["id"] != workspace_id] + [archived])
        self.store.update("workspaces", [], lambda items: [w for w in items if w["id"] != workspace_id])
        return {"id": workspace_id, "deleted": True, "source_files_preserved": True}

    def list(self, owner_id: str = "") -> List[Workspace]:
        result = []
        for item in self.store.read("workspaces", []):
            normalized = dict(item, owner_id=item.get("owner_id", ""))
            if owner_id and normalized.get("owner_id") != owner_id and not self._local_legacy(owner_id, normalized):
                continue
            result.append(Workspace(**normalized))
        return result

    def get(self, workspace_id: str, task_id: str = "", owner_id: str = "") -> Workspace:
        if task_id:
            self.get(workspace_id, owner_id=owner_id)
            for task in self.store.read("tasks", []):
                if task["id"] == task_id:
                    snapshot = task.get("workspace_snapshot")
                    if owner_id and task.get("owner_id") != owner_id:
                        raise PermissionError("无权访问该工程")
                    if task["workspace_id"] != workspace_id or not snapshot or snapshot.get("id") != workspace_id:
                        raise ValueError("task has no matching workspace snapshot; create or approve the task again")
                    if owner_id:
                        self.get(workspace_id, owner_id=owner_id)
                        if (snapshot.get("owner_id") or task.get("owner_id", "")) != owner_id:
                            raise PermissionError("无权访问工程快照")
                    self._check_root(snapshot["root"])
                    return Workspace(**dict(snapshot, owner_id=snapshot.get("owner_id") or task.get("owner_id", "")))
            raise KeyError("task not found")
        for workspace in self.list(owner_id):
            if workspace.id == workspace_id:
                self._check_root(workspace.root)
                return workspace
        if owner_id and any(item.get("id") == workspace_id for item in self.store.read("workspaces", [])):
            raise PermissionError("无权访问该工程")
        raise KeyError("workspace not found")

    @staticmethod
    def _local_legacy(owner_id, item):
        return owner_id == "local" and not item.get("owner_id") and os.environ.get("CODESPIDER_AUTH_REQUIRED") != "1"

    @staticmethod
    def _check_root(root):
        if os.path.realpath(root) != root:
            raise PermissionError("工程目录链接已改变，请重新配置工程")

    @staticmethod
    def owner_base(owner_id=""):
        if owner_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", owner_id):
            raise ValueError("invalid owner id")
        base = os.path.realpath(os.path.expanduser("~/.codespider/project"))
        target = os.path.join(base, owner_id) if owner_id else base
        if os.path.realpath(target) != target:
            raise PermissionError("用户工程目录不能是符号链接")
        return target

    def _validate_location(self, root, owner_id, items, workspace_id="", allow_external=True):
        base = self.owner_base(owner_id)
        state_root = os.path.realpath(self.store.root)
        if owner_id and owner_id != "local" and os.path.commonpath([base, root]) != base and os.path.commonpath([state_root, root]) in (state_root, root):
            raise PermissionError("工程目录不能覆盖服务持久数据目录")
        if owner_id and not allow_external and os.path.commonpath([base, root]) != base:
            raise PermissionError("只能在自己的工程目录中创建或打开项目")
        if root == base:
            raise PermissionError("请选择用户工程目录下的具体项目")
        reserved = self.owner_base()
        if owner_id and os.path.commonpath([reserved, root]) == reserved and os.path.commonpath([base, root]) != base:
            # Existing legacy locations can be retained by their assigned owner.
            if not any(w["id"] == workspace_id and w.get("owner_id") == owner_id and w["root"] == root for w in items):
                raise PermissionError("不能访问其他用户的工程目录")
        protected = list(items)
        protected.extend(self.store.read("deleted_workspaces", []))
        protected.extend(dict(t.get("workspace_snapshot", {}), owner_id=t.get("owner_id", ""))
                         for t in self.store.read("tasks", []) if t.get("workspace_snapshot"))
        for item in protected:
            if item.get("owner_id", "") == owner_id or self._local_legacy(owner_id, item):
                continue
            other = os.path.realpath(item["root"])
            if os.path.commonpath([root, other]) in (root, other):
                raise PermissionError("工程目录不能与其他用户的工程重叠")

    def create(self, root: str = "", name: Optional[str] = None, start_command: str = "", description: str = "", execution_mode: str = "safe", command_allowlist: Optional[List[str]] = None, owner_id: str = "", allow_external: bool = True) -> Workspace:
        if not isinstance(root, str) or (name is not None and not isinstance(name, str)):
            raise ValueError("工程位置和项目名称必须为文本")
        root, name = root.strip(), (name or "").strip()
        base = self.owner_base(owner_id)
        if not root and (not name or name in (".", "..") or any(c in name for c in ("/", "\\", "\0"))):
            raise ValueError("使用默认位置时，请填写项目名称，且名称不能包含路径分隔符")
        real_root = os.path.realpath(os.path.expanduser(root)) if root else os.path.realpath(os.path.join(base, name))
        if not root and os.path.dirname(real_root) != base:
            raise ValueError("默认项目位置不能指向项目目录之外")
        workspace = None
        def register(items):
            nonlocal workspace
            self._validate_location(real_root, owner_id, items, allow_external=allow_external)
            if not root:
                os.makedirs(real_root, exist_ok=True)
            if not os.path.isdir(real_root):
                raise ValueError("workspace root must be an existing directory")
            workspace = Workspace(id=new_id("ws"), name=name or os.path.basename(real_root), root=real_root,
                project_type=detect_project(real_root)["type"], start_command=start_command, description=description,
                execution_mode=execution_mode if execution_mode in WorkspacePolicy.MODES else "safe",
                command_allowlist=command_allowlist or [], owner_id=owner_id)
            CodeIndexer(real_root, WorkspacePolicy(real_root)).build()
            return items + [workspace.to_dict()]
        self.store.update("workspaces", [], register)
        return workspace

    def update(self, workspace_id: str, *args, **kwargs) -> Workspace:
        with self.lease(workspace_id):
            return self._update(workspace_id, *args, **kwargs)

    def _update(self, workspace_id: str, name: str, root: str, start_command: str, description: str, execution_mode: str = "safe", command_allowlist: Optional[List[str]] = None, owner_id: str = "", allow_external: bool = True) -> Workspace:
        updated = None
        def replace(items):
            nonlocal updated
            item = next((w for w in items if w["id"] == workspace_id), None)
            if not item:
                raise KeyError("workspace not found")
            if owner_id and item.get("owner_id") != owner_id and not self._local_legacy(owner_id, item):
                raise PermissionError("无权访问该工程")
            workspace = Workspace(**item)
            real_root = os.path.realpath(os.path.expanduser(root))
            self._validate_location(real_root, workspace.owner_id, items, workspace_id,
                allow_external=allow_external or real_root == workspace.root)
            if not os.path.isdir(real_root):
                raise ValueError("workspace root must be an existing directory")
            if real_root != workspace.root:
                workspace.root = real_root
                workspace.project_type = detect_project(real_root)["type"]
                CodeIndexer(real_root, WorkspacePolicy(real_root)).build()
            workspace.name = name.strip() or os.path.basename(real_root)
            workspace.start_command, workspace.description = start_command.strip(), description.strip()
            workspace.execution_mode = execution_mode if execution_mode in WorkspacePolicy.MODES else "safe"
            workspace.command_allowlist = [x.strip() for x in (command_allowlist or []) if x and x.strip()]
            updated = workspace
            return [workspace.to_dict() if w["id"] == workspace_id else w for w in items]
        self.store.update("workspaces", [], replace)
        return updated

    def migrate_legacy_ownership(self, owner_id: str) -> int:
        """Assign pre-authentication workspaces to the first administrator once."""
        if not owner_id:
            return 0
        changed = 0
        def migrate(items):
            nonlocal changed
            result = []
            for item in items:
                if not item.get("owner_id"):
                    owners = {t["owner_id"] for t in self.store.read("tasks", []) if t.get("workspace_id") == item["id"] and t.get("owner_id")}
                    assigned = next(iter(owners)) if len(owners) == 1 else owner_id
                    item = dict(item, owner_id=assigned)
                    changed += 1
                result.append(item)
            return result
        self.store.update("workspaces", [], migrate)
        return changed

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
