import tempfile
import time
import unittest
from pathlib import Path

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

