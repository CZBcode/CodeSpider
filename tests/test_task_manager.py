import tempfile
import time
import unittest
from pathlib import Path
from backend.tool_protocol import ToolRequest, ToolResponse

from backend.app import AppContext


class TaskManagerTests(unittest.TestCase):
    def test_approved_patch_is_applied_and_verified(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as data:
            Path(root, "main.py").write_text("value = 1\n", encoding="utf-8")
            context = AppContext(data)
            workspace = context.workspaces.create(root)
            task = context.tasks.create(workspace.id, "更新值", patches=[{"path": "main.py", "expected": "value = 1\n", "replacement": "value = 2\n"}])
            context.tasks.approve(task.id)
            for _ in range(50):
                current = context.tasks.get(task.id)
                if current.status in ("succeeded", "failed", "cancelled"):
                    break
                time.sleep(0.02)
            self.assertEqual(current.status, "succeeded")
            self.assertEqual(Path(root, "main.py").read_text(encoding="utf-8"), "value = 2\n")
            self.assertIn("file.changed", [event.type for event in context.tasks.events(task.id)])

    def test_retryable_tool_failure_retries_twice_and_keeps_details_collapsed(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as data:
            context = AppContext(data)
            workspace = context.workspaces.create(root)
            task = context.tasks.create(workspace.id, "重试工具调用")

            class FlakyTools:
                def __init__(self):
                    self.calls = 0

                def call(self, request):
                    self.calls += 1
                    if self.calls < 3:
                        return ToolResponse(request.request_id, False, error={"message": "temporary agent failure", "retryable": True})
                    return ToolResponse(request.request_id, True, {"ok": True})

            flaky = FlakyTools()
            original = context.tasks.tools
            context.tasks.tools = flaky
            try:
                response = context.tasks._call_tool(task.id, ToolRequest("code", "index", workspace_id=workspace.id, task_id=task.id))
            finally:
                context.tasks.tools = original
                context.tasks.executor.shutdown(wait=True)
            self.assertTrue(response.ok)
            self.assertEqual(flaky.calls, 3)
            events = context.tasks.events(task.id)
            calls = [event for event in events if event.type == "tool.call"]
            retries = [event for event in events if event.type == "tool.retry"]
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(retries), 2)
            self.assertTrue(all(event.payload["collapsed"] for event in calls + retries))

    def test_failed_command_retries_twice_before_returning_final_result(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as data:
            context = AppContext(data)
            workspace = context.workspaces.create(root)
            task = context.tasks.create(workspace.id, "重试执行命令")

            class FlakyCommand:
                def __init__(self):
                    self.calls = 0

                def call(self, request):
                    self.calls += 1
                    code = 1 if self.calls < 3 else 0
                    return ToolResponse(request.request_id, True, {"exit_code": code, "output": "temporary connection timeout"})

            command = FlakyCommand()
            original = context.tasks.tools
            context.tasks.tools = command
            try:
                response = context.tasks._call_tool(task.id, ToolRequest("process", "run", {"command": "mvn -q test"}, workspace_id=workspace.id, task_id=task.id))
            finally:
                context.tasks.tools = original
                context.tasks.executor.shutdown(wait=True)
            self.assertEqual(response.data["exit_code"], 0)
            self.assertEqual(response.data["attempts"], 3)
            self.assertEqual(len([event for event in context.tasks.events(task.id) if event.type == "tool.retry"]), 2)
