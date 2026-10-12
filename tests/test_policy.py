import os
import tempfile
import unittest

from backend.policy import ApprovalRequired, PolicyError, WorkspacePolicy


class PolicyTests(unittest.TestCase):
    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as root:
            policy = WorkspacePolicy(root)
            with self.assertRaises(PolicyError):
                policy.resolve("../outside.txt")

    def test_classifies_commands(self):
        with tempfile.TemporaryDirectory() as root:
            policy = WorkspacePolicy(root)
            self.assertEqual(policy.command_risk("python3 -m compileall -q ."), "low")
            self.assertEqual(policy.command_risk("pip install requests"), "confirm")
            with self.assertRaises(PolicyError):
                policy.validate_command("rm -rf .")

    def test_safe_mode_requires_approval_unless_allowlisted(self):
        with tempfile.TemporaryDirectory() as root:
            policy = WorkspacePolicy(root, mode="safe", command_allowlist=["python3 -m pytest"])
            with self.assertRaises(ApprovalRequired):
                policy.validate_command("python3 -m compileall -q .")
            risk, tokens = policy.validate_command("python3 -m pytest tests/test_policy.py")
            self.assertEqual(risk, "low")
            self.assertEqual(tokens[:3], ["python3", "-m", "pytest"])
            with self.assertRaises(ApprovalRequired):
                policy.validate_read("README.md")

    def test_divergent_mode_only_prompts_for_high_risk(self):
        with tempfile.TemporaryDirectory() as root:
            policy = WorkspacePolicy(root, mode="divergent")
            self.assertEqual(policy.validate_command("python3 -m compileall -q .")[0], "low")
            with self.assertRaises(ApprovalRequired):
                policy.validate_command("rm -rf build")
