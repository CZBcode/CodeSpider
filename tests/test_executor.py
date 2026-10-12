import os
import tempfile
import unittest

from agent_client.executor import AgentExecutor, ExecutionError
from backend.policy import PolicyError, WorkspacePolicy


class ExecutorTests(unittest.TestCase):
    def test_patch_requires_approval_and_expected_content(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "hello.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("old")
            executor = AgentExecutor(WorkspacePolicy(root))
            with self.assertRaises(PolicyError):
                executor.apply_patch("hello.txt", "old", "new")
            executor.apply_patch("hello.txt", "old", "new", approved=True)
            self.assertEqual(executor.read_file("hello.txt", approved=True), "new")
            with self.assertRaises(ExecutionError):
                executor.apply_patch("hello.txt", "old", "again", approved=True)
