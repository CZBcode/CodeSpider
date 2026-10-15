import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import AppContext
from backend.tool_protocol import ToolRequest
from codespider.ipc import request
from tests.test_task_regressions import wait_until, override_verification


class RemoteTaskTests(unittest.TestCase):
    def test_cancel_reaches_independent_agent_and_reaps_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data, root, socket = base / 'data', base / 'project', base / 'agent.sock'
            root.mkdir()
            (root / 'main.py').write_text('value = 1\n')
            token = 'isolated-regression-test-token'
            context, task = None, None
            with open(base / 'agent.log', 'w') as log:
                child = subprocess.Popen([sys.executable, '-m', 'agent_client.server',
                    '--data-dir', str(data), '--socket', str(socket)],
                    cwd=Path(__file__).resolve().parent.parent,
                    env=dict(os.environ, CODESPIDER_IPC_TOKEN=token), stdout=log, stderr=log)
                try:
                    wait_until(socket.exists)
                    self.assertEqual(request(socket, token, 'GET', '/health')['pid'], child.pid)
                    with patch.dict(os.environ, {'CODESPIDER_IPC_TOKEN': token}):
                        context = AppContext(str(data), str(socket))
                    workspace = context.workspaces.create(str(root))
                    rejected = context.tools.call({'tool': 'workspace', 'action': 'read_file',
                        'workspace_id': workspace.id, 'arguments': {'path': 'main.py'},
                        'approval': {'approved': 'false'}})
                    self.assertFalse(rejected.ok)
                    script = "import os,time; from pathlib import Path; Path('pid').write_text(str(os.getpid())); time.sleep(10); Path('late').write_text('bad')"
                    override_verification(context, shlex.quote(sys.executable) + ' -c ' + shlex.quote(script))
                    task = context.tasks.create(workspace.id, 'cancel independent Agent command')
                    context.tasks.approve(task.id)
                    wait_until(lambda: (root / 'pid').exists())
                    pid = int((root / 'pid').read_text())
                    self.assertEqual(context.tasks.cancel(task.id).status, 'cancelled')
                    with self.assertRaises(ProcessLookupError):
                        os.kill(pid, 0)
                    context.tasks.executor.shutdown(wait=True)
                    self.assertEqual(context.tasks.get(task.id).status, 'cancelled')
                    self.assertFalse((root / 'late').exists())
                    self.assertNotIn('task.succeeded', [e.type for e in context.tasks.events(task.id)])
                    late = context.tools.call(ToolRequest('workspace', 'write_file', {'path': 'late.txt', 'content': 'bad'},
                        task_id=task.id, workspace_id=workspace.id, approval={'approved': True}))
                    self.assertFalse(late.ok)
                    self.assertFalse((root / 'late.txt').exists())
                finally:
                    if context:
                        if task and context.tasks.get(task.id).status in ('executing', 'cancelling'):
                            context.tasks.cancel(task.id)
                        context.tasks.executor.shutdown(wait=True)
                        context.processes.close()
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
