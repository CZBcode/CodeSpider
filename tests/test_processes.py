import tempfile
import unittest

from agent_client.processes import ProcessManager
from backend.policy import WorkspacePolicy


class ProcessTests(unittest.TestCase):
    def test_start_and_stop_process_without_shell(self):
        with tempfile.TemporaryDirectory() as root:
            manager = ProcessManager()
            item = manager.start(WorkspacePolicy(root), 'python3 -c "import time; time.sleep(5)"', approved=True)
            self.assertEqual(item["status"], "running")
            stopped = manager.stop(item["pid"])
            self.assertEqual(stopped["status"], "stopped")
