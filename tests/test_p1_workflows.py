import concurrent.futures
import fcntl
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_client.executor import AgentExecutor, ExecutionError
from backend.app import AppContext
from backend.policy import WorkspacePolicy
from backend.tool_protocol import ToolRequest, ToolResponse


class P1WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'original'
        self.root.mkdir()
        self.context = AppContext(str(self.base / 'data'))
        self.addCleanup(self.context.processes.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)

    def test_running_task_keeps_original_root_policy_and_verification_directory(self):
        (self.root / 'main.py').write_text('value=1\n')
        other = self.base / 'other'
        other.mkdir()
        (other / 'main.py').write_text('value=1\n')
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'edit original', [
            {'path': 'main.py', 'expected': 'value=1\n', 'replacement': 'value=2\n'}])
        started, resume = threading.Event(), threading.Event()
        original = self.context.tools._workspace
        def delayed(request):
            started.set()
            if not resume.wait(5):
                raise RuntimeError('test barrier timeout')
            return original(request)
        command = shlex.quote(sys.executable) + ' -c ' + shlex.quote("from pathlib import Path; Path('verified').write_text(str(Path.cwd()))")
        from tests.test_task_regressions import override_verification
        override_verification(self.context, command)
        try:
            with patch.object(self.context.tools, '_workspace', side_effect=delayed):
                self.context.tasks.approve(task.id)
                self.assertTrue(started.wait(5))
                self.context.workspaces.update(workspace.id, 'moved', str(other), '', '', 'divergent', ['python3'])
                resume.set()
                self.context.tasks.executor.shutdown(wait=True)
        finally:
            resume.set()
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        self.assertEqual((self.root / 'main.py').read_text(), 'value=2\n')
        self.assertEqual((other / 'main.py').read_text(), 'value=1\n')
        self.assertEqual((self.root / 'verified').read_text(), str(self.root.resolve()))
        self.assertFalse((other / 'verified').exists())
        self.assertEqual(self.context.workspaces.policy(workspace.id, task.id).mode, 'safe')
        self.assertEqual(self.context.workspaces.policy(workspace.id, task.id).command_allowlist, ())

    def test_pending_task_snapshot_survives_settings_change_and_reload(self):
        (self.root / 'main.py').write_text('value=1\n')
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'old target', [{'path': 'new.txt', 'content': 'ok'}])
        other = self.base / 'other'
        other.mkdir()
        self.context.workspaces.update(workspace.id, 'other', str(other), '', '', 'divergent')
        self.assertEqual(self.context.tasks.get(task.id).workspace_snapshot['root'], str(self.root.resolve()))
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        self.assertTrue((self.root / 'new.txt').exists())
        self.assertFalse((other / 'new.txt').exists())
        # Type refresh for the old root must not rewrite the new root's metadata.
        self.assertEqual(self.context.workspaces.get(workspace.id).project_type, 'unknown')

    def test_unknown_task_id_and_mismatched_workspace_cannot_select_a_snapshot(self):
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'original')
        for task_id, workspace_id in [('missing', workspace.id), (task.id, 'wrong-workspace')]:
            result = self.context.tools.call(ToolRequest('workspace', 'write_file', {'path': 'wrong.txt', 'content': 'bad'},
                task_id=task_id, workspace_id=workspace_id, approval={'approved': True}))
            self.assertFalse(result.ok)
        self.assertFalse((self.root / 'wrong.txt').exists())

    def test_new_python_project_with_syntax_error_fails_real_verification(self):
        workspace = self.context.workspaces.create(str(self.root))
        self.assertEqual(workspace.project_type, 'unknown')
        task = self.context.tasks.create(workspace.id, 'generate Python', [{'path': 'main.py', 'content': 'def broken(\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        self.assertEqual(self.context.workspaces.get(workspace.id).project_type, 'python')
        self.assertIn(1, [e.payload['exit_code'] for e in self.context.tasks.events(task.id) if e.type == 'process.output'])

    def test_new_valid_python_project_is_verified(self):
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'generate Python', [{'path': 'main.py', 'content': 'value=1\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        self.assertEqual(self.context.workspaces.get(workspace.id).project_type, 'python')
        self.assertIn(0, [e.payload['exit_code'] for e in self.context.tasks.events(task.id) if e.type == 'process.output'])

    def test_unrecognized_generated_project_does_not_claim_verified_success(self):
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'unknown output', [{'path': 'source.xyz', 'content': 'unknown'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        result = self.context.tasks.get(task.id)
        self.assertEqual(result.status, 'failed')
        self.assertIn('未执行验证', result.error)

    def test_generated_java_and_vue_select_their_verification_commands(self):
        # Verify routing without requiring Maven/Node installations.
        original = self.context.tools.call
        commands = []
        def capture(request):
            if request.tool == 'process' and request.action == 'run':
                commands.append(request.arguments['command'])
                return ToolResponse(request.request_id, True, {'exit_code': 0, 'output': ''})
            return original(request)
        with patch.object(self.context.tools, 'call', side_effect=capture):
            tasks = []
            for name, filename, content in [('java', 'pom.xml', '<project/>'), ('vue', 'package.json', '{"dependencies":{"vue":"3"}}')]:
                root = self.base / name
                root.mkdir()
                workspace = self.context.workspaces.create(str(root))
                task = self.context.tasks.create(workspace.id, 'generate', [{'path': filename, 'content': content}])
                tasks.append(task)
                self.context.tasks.approve(task.id)
            self.context.tasks.executor.shutdown(wait=True)
        self.assertCountEqual(commands, ['mvn -q test', 'npm install --ignore-scripts --no-audit --no-fund', 'npm run build'])
        self.assertTrue(all(self.context.tasks.get(t.id).status == 'succeeded' for t in tasks))


class ConcurrentPatchTests(unittest.TestCase):
    def test_plain_write_waits_for_file_lock_before_truncating(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root, 'file.txt')
            target.write_text('keep until unlocked')
            with target.open('r+') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    entered = threading.Event()
                    def write():
                        entered.set()
                        return AgentExecutor(WorkspacePolicy(root)).write_file('file.txt', 'new', approved=True)
                    future = pool.submit(write)
                    try:
                        self.assertTrue(entered.wait(2))
                        with self.assertRaises(concurrent.futures.TimeoutError):
                            future.result(timeout=.1)
                        self.assertEqual(target.read_text(), 'keep until unlocked')
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                    future.result(timeout=2)
            self.assertEqual(target.read_text(), 'new')

    def test_competing_patches_across_processes_accept_only_one_expected_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'main.txt').write_text('old')
            script = '''import sys,time
from pathlib import Path
from agent_client.executor import AgentExecutor, ExecutionError
from backend.policy import WorkspacePolicy
root=Path(sys.argv[1]); name=sys.argv[2]
(root/('ready'+name)).touch()
while not (root/'go').exists(): time.sleep(.01)
try:
    AgentExecutor(WorkspacePolicy(str(root))).apply_patch('main.txt','old','new'+name,approved=True)
    print('written')
except ExecutionError:
    print('conflict')
'''
            children = [subprocess.Popen([sys.executable, '-c', script, str(root), str(n)],
                cwd=Path(__file__).resolve().parent.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(6)]
            try:
                deadline = time.monotonic() + 5
                while len(list(root.glob('ready*'))) < 6 and time.monotonic() < deadline:
                    time.sleep(.01)
                (root / 'go').touch()
                results = [child.communicate(timeout=10) for child in children]
                self.assertTrue(all(child.returncode == 0 for child in children), results)
                self.assertEqual([out.strip() for out, _ in results].count('written'), 1)
                self.assertEqual([out.strip() for out, _ in results].count('conflict'), 5)
                self.assertIn((root / 'main.txt').read_text(), ['new%s' % n for n in range(6)])
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait()

    def test_patch_truncates_shorter_unicode_content_correctly(self):
        with tempfile.TemporaryDirectory() as root:
            executor = AgentExecutor(WorkspacePolicy(root))
            executor.write_file('text.txt', '较长的原始文本\n', approved=True)
            executor.apply_patch('text.txt', '较长的原始文本\n', '新\n', approved=True)
            self.assertEqual(Path(root, 'text.txt').read_text(), '新\n')
