import concurrent.futures
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from codespider.daemon import runtime_dir, saved_state
from codespider.ipc import request


ROOT = Path(__file__).resolve().parent.parent


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def eventually(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    raise AssertionError("condition did not become true")


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.url = 'http://127.0.0.1:%s' % self.port

    def tearDown(self):
        self.cli('stop', check=False)
        self.temp.cleanup()

    def cli(self, command, *arguments, check=True):
        result = subprocess.run([sys.executable, '-m', 'codespider', command,
            '--data-dir', str(self.data), *arguments], cwd=ROOT,
            capture_output=True, text=True, timeout=40)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def api(self, path, body=None, expected=200):
        req = urllib.request.Request(self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            response = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            self.assertEqual(response.status, expected)
            return json.load(response)

    def status(self):
        return json.loads(self.cli('status', '--json').stdout)

    def test_lifecycle_agent_tools_and_persistence(self):
        self.cli('start', '--port', str(self.port))
        state = self.status()
        self.assertEqual(len({state['pid'], *[child['pid'] for child in state['children'].values()]}), 3)
        self.cli('start', '--port', str(self.port))
        self.assertEqual(self.status()['instance'], state['instance'])
        self.assertEqual(self.cli('restart', '--port', '0', check=False).returncode, 1)
        self.assertEqual(self.status()['instance'], state['instance'])
        health = self.api('/api/health')
        self.assertEqual(health['agent']['pid'], state['children']['agent']['pid'])
        for path in ('/', '/app.js', '/style.css'):
            with urllib.request.urlopen(self.url + path) as response:
                self.assertGreater(len(response.read()), 100)
        with self.assertRaises(ValueError):
            request(runtime_dir(self.data) / 'agent.sock', 'incorrect-token', 'GET', '/health')
        workspace = self.api('/api/workspaces', {'root': str(self.project)}, 201)['id']
        payload = {'tool': 'workspace', 'action': 'write_file', 'workspace_id': workspace,
                   'arguments': {'path': 'hello.py', 'content': 'print("hello")\n'}}
        self.assertFalse(self.api('/api/tools/call', payload, 400)['ok'])
        payload['approval'] = {'approved': True}
        self.assertTrue(self.api('/api/tools/call', payload)['ok'])
        self.assertEqual((self.project / 'hello.py').read_text(), 'print("hello")\n')
        command = shlex.quote(sys.executable) + ' -c "import os; print(os.getppid())"'
        result = self.api('/api/workspaces/' + workspace + '/run', {'command': command, 'approved': True})
        self.assertEqual(int(result['output'].strip()), health['agent']['pid'])
        result = self.api('/api/tools/call', {'tool': 'workspace', 'action': 'read_file',
            'workspace_id': workspace, 'arguments': {'path': 'missing.txt'}, 'approval': {'approved': True}}, 400)
        self.assertEqual(result['error']['code'], 'TOOL_ERROR')
        service = self.api('/api/workspaces/' + workspace + '/processes', {
            'command': shlex.quote(sys.executable) + ' -c "import time; time.sleep(120)"', 'approved': True}, 201)
        self.assertEqual(self.api('/api/workspaces/' + workspace + '/processes')['items'][0]['pid'], service['pid'])
        self.api('/api/settings', {'model': 'local-test-model', 'api_key': 'test-only-not-a-real-key'})
        self.cli('restart', '--port', str(self.port))
        eventually(lambda: not alive(service['pid']))
        self.assertEqual(self.api('/api/settings')['model'], 'local-test-model')
        self.assertEqual(self.api('/api/workspaces')['items'][0]['id'], workspace)
        self.assertTrue((self.project / 'hello.py').exists())

        # Stop while a synchronous command is active; its process must not leak.
        command = shlex.quote(sys.executable) + ' -c ' + shlex.quote(
            "import os,time; from pathlib import Path; Path('command.pid').write_text(str(os.getpid())); time.sleep(120)")
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.api, '/api/workspaces/' + workspace + '/run', {'command': command, 'approved': True})
            eventually(lambda: (self.project / 'command.pid').exists())
            command_pid = int((self.project / 'command.pid').read_text())
            state = self.status()
            self.cli('stop')
            # The web request can be interrupted while services shut down.
            try:
                future.result()
            except (OSError, AssertionError):
                pass
        for pid in [command_pid, *[child['pid'] for child in state['children'].values()]]:
            eventually(lambda: not alive(pid))
        self.assertEqual(self.cli('status', check=False).returncode, 1)
        self.assertTrue((self.data / 'settings.json').exists())

    def test_occupied_port_fails_without_touching_owner(self):
        with socket.socket() as owner:
            owner.bind(('127.0.0.1', self.port))
            owner.listen()
            result = self.cli('start', '--port', str(self.port), check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn('启动失败', result.stderr)
            self.assertEqual(owner.getsockname()[1], self.port)
            self.assertEqual(saved_state(self.data)['status'], 'failed')
            self.assertFalse((runtime_dir(self.data) / 'agent.sock').exists())

    def test_agent_exit_stops_web_and_reports_failure(self):
        self.cli('start', '--port', str(self.port))
        state = self.status()
        os.kill(state['children']['agent']['pid'], signal.SIGTERM)
        eventually(lambda: saved_state(self.data).get('status') == 'failed')
        eventually(lambda: not alive(state['children']['web']['pid']))
        self.assertEqual(self.cli('status', check=False).returncode, 1)

    def test_http_approval_validation_concurrency_and_failed_verification(self):
        (self.project / 'main.py').write_text('value=1\n')
        self.cli('start', '--port', str(self.port))
        workspace = self.api('/api/workspaces', {'root': str(self.project)}, 201)['id']
        command = shlex.quote(sys.executable) + ' -c ' + shlex.quote("from pathlib import Path; Path('unapproved').touch()")
        for approved in ('false', 1, None):
            self.api('/api/workspaces/' + workspace + '/run', {'command': command, 'approved': approved}, 400)
            self.api('/api/tools/call', {'tool': 'process', 'action': 'run', 'workspace_id': workspace,
                'arguments': {'command': command}, 'approval': {'approved': approved}}, 400)
        self.assertFalse((self.project / 'unapproved').exists())
        self.api('/api/workspaces/' + workspace + '/run', {'command': command, 'approved': False}, 409)
        self.api('/api/documents/generate', {'workspace_id': workspace, 'approved': 'false'}, 400)
        self.assertFalse((self.project / 'CODESPIDER.md').exists())
        self.api('/api/tasks', {'workspace_id': workspace, 'goal': 123}, 400)

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            tasks = list(pool.map(lambda n: self.api('/api/tasks', {'workspace_id': workspace, 'goal': 'task %s' % n}, 201), range(24)))
        for task in tasks:
            self.assertEqual(self.api('/api/tasks/' + task['id'])['goal'], task['goal'])

        failed = self.api('/api/tasks', {'workspace_id': workspace, 'goal': 'invalid syntax',
            'patches': [{'path': 'bad.py', 'content': 'def broken(\n'}]}, 201)
        self.api('/api/tasks/' + failed['id'] + '/approve', {})
        eventually(lambda: self.api('/api/tasks/' + failed['id'])['status'] == 'failed')
        self.api('/api/tasks/' + failed['id'] + '/cancel', {}, 400)
        self.assertEqual(self.api('/api/tasks/' + failed['id'])['status'], 'failed')

    def test_remote_task_uses_snapshot_and_detects_new_project_type(self):
        self.cli('start', '--port', str(self.port))
        workspace = self.api('/api/workspaces', {'root': str(self.project)}, 201)
        task = self.api('/api/tasks', {'workspace_id': workspace['id'], 'goal': 'generate invalid Python',
            'patches': [{'path': 'main.py', 'content': 'def broken(\n'}]}, 201)
        self.assertEqual(task['workspace_snapshot']['root'], str(self.project.resolve()))
        other = Path(self.temp.name) / 'other'
        other.mkdir()
        self.api('/api/workspaces/' + workspace['id'] + '/settings', dict(workspace, root=str(other)))
        self.api('/api/tasks/' + task['id'] + '/approve', {})
        eventually(lambda: self.api('/api/tasks/' + task['id'])['status'] == 'failed')
        self.assertTrue((self.project / 'main.py').exists())
        self.assertFalse((other / 'main.py').exists())
        events = self.api('/api/tasks/' + task['id'] + '/events')['items']
        self.assertIn('python', [event['payload']['project_type'] for event in events if event['type'] == 'project.detected'])
        self.assertIn(1, [event['payload']['exit_code'] for event in events if event['type'] == 'process.output'])
        # Detection in the original directory must not change the new location's type.
        self.assertEqual(self.api('/api/workspaces')['items'][0]['project_type'], 'unknown')


class MultiprocessStoreTests(unittest.TestCase):
    def test_memory_writes_from_multiple_processes_are_not_lost(self):
        with tempfile.TemporaryDirectory() as data:
            script = ('import sys; from backend.store import JsonStore; from memory.service import MemoryService; '
                      'memory=MemoryService(JsonStore(sys.argv[1])); '
                      '[memory.add_short_term(sys.argv[2], {"n": n}) for n in range(30)]')
            children = [subprocess.Popen([sys.executable, '-c', script, data, str(n)], cwd=ROOT) for n in range(4)]
            for child in children:
                self.assertEqual(child.wait(timeout=10), 0)
            items = json.loads(Path(data, 'memories.json').read_text())
            self.assertEqual(len(items), 120)
            self.assertEqual(len({(item['scope_id'], item['content']['n']) for item in items}), 120)
