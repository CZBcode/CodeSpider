import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from agent_client.executor import ExecutionError
from backend.models import Event, Task, new_id, now_iso
from memory.service import MemoryService
from backend.model_gateway import ModelGateway
from backend.tool_protocol import ToolRequest


class TaskManager:
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

    def create(self, workspace_id: str, goal: str, patches: Optional[List[Dict[str, Any]]] = None) -> Task:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal cannot be empty")
        workspace = self.workspaces.get(workspace_id)
        turn = self._make_turn(workspace, goal)
        task = Task(new_id("task"), workspace_id, goal.strip(), plan=turn["steps"], patches=patches or turn.get("patches", []), thinking=turn["thinking"], tool_calls=turn.get("tool_calls", []), response_schema=turn.get("schema", "agent.turn/v1"))
        task.workspace_snapshot = workspace.to_dict()
        self._save_task(task)
        self._emit(task.id, "task.created", {"goal": task.goal})
        self._emit(task.id, "task.plan_ready", {"schema": task.response_schema, "thinking": task.thinking, "steps": task.plan, "tool_calls": task.tool_calls})
        return task

    def _make_turn(self, workspace: Any, goal: str) -> Dict[str, Any]:
        generated = self.model.validate_turn(self.model.plan(goal, {"project_type": workspace.project_type}))
        details = [
            {"step": 1, "title": "理解工作区", "action": "index", "detail": "读取工程类型、文件和相关符号"},
            {"step": 2, "title": "执行用户目标", "action": "agent", "detail": goal},
            {"step": 3, "title": "验证结果", "action": "verify", "detail": "根据工程类型运行测试或检查命令"},
        ]
        for index, item in enumerate(generated.get("steps", []), 1):
            detail_index = index - 1
            if detail_index < len(details):
                details[detail_index]["action"] = item.get("action", details[detail_index]["action"])
                details[detail_index]["title"] = item.get("title", details[detail_index]["title"])
                details[detail_index]["detail"] = item.get("detail", details[detail_index]["detail"])
        generated["steps"] = details
        generated.setdefault("thinking", [{"id": "plan", "title": "制定步骤", "summary": "准备执行工程任务", "status": "pending"}])
        generated.setdefault("tool_calls", [])
        generated.setdefault("patches", [])
        generated.setdefault("schema", "agent.turn/v1")
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
                for patch in task.patches:
                    if "expected" in patch:
                        request = ToolRequest(tool="workspace", action="apply_patch", workspace_id=task.workspace_id, task_id=task_id, arguments={"path": patch.get("path", ""), "expected": patch.get("expected", ""), "replacement": patch.get("replacement", "")}, approval={"approved": True, "source": "task_approval"})
                    else:
                        request = ToolRequest(tool="workspace", action="write_file", workspace_id=task.workspace_id, task_id=task_id, arguments={"path": patch.get("path", ""), "content": patch.get("content", "")}, approval={"approved": True, "source": "task_approval"})
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
            if verify_command:
                request = ToolRequest(tool="process", action="run", workspace_id=task.workspace_id, task_id=task_id, arguments={"command": verify_command, "timeout": 30}, approval={"approved": True, "source": "task_approval"})
                result = self._call_tool(task_id, request)
                self._emit(task_id, "process.output", result.data)
                if result.data.get("exit_code") != 0:
                    raise ExecutionError("verification failed (exit code %s): %s" % (result.data.get("exit_code"), verify_command))
            completion_message = "任务完成。" if task.patches else "任务完成，当前任务没有提供文件补丁。"
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
                task.status = "failed"
                task.error = str(exc)
                task.updated_at = now_iso()
                self._save_task(task)
                self._emit(task_id, "task.failed", {"error": str(exc)})

    def _call_tool(self, task_id: str, request: ToolRequest):
        if self.tools is None:
            raise RuntimeError("tool service is not configured")
        with self._lock:
            if task_id in self._cancelled:
                raise ExecutionError("task cancelled")
            self._emit(task_id, "tool.call", {"request": request.to_dict(), "collapsed": True})
        response = self.tools.call(request)
        self._emit(task_id, "tool.result", response.to_dict())
        if not response.ok:
            message = response.error.get("message", "tool call failed") if response.error else "tool call failed"
            raise ValueError(message)
        return response

    @staticmethod
    def _default_verify(project_type: str) -> Optional[str]:
        return {"python": "python3 -m compileall -q .", "java-springboot": "mvn -q -DskipTests compile", "vue": "npm run build"}.get(project_type)
