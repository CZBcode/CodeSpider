"""Real H2 + daemon + Agent persistence, without paid model calls or live user data."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile

from backend.h2_store import find_h2_jar


@unittest.skipUnless(find_h2_jar(), 'H2 JDBC jar unavailable')
class PersistenceHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codespider-persistence-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.project = self.root / 'project'
        self.project.mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.env = dict(os.environ, CODESPIDER_AUTH_REQUIRED='1', CODESPIDER_H2_JAR=find_h2_jar())
        self.addCleanup(lambda: self.cli('stop', check=False))
        self.cli('start')
        self.browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def cli(self, action, check=True):
        result = subprocess.run([sys.executable, '-m', 'codespider', action,
            '--data-dir', str(self.data), *(['--port', str(self.port)] if action != 'stop' else [])],
            cwd=Path(__file__).resolve().parent.parent, env=self.env, capture_output=True, text=True, timeout=45)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def request(self, path, body=None, expected=200, raw=False):
        req = urllib.request.Request('http://127.0.0.1:%s%s' % (self.port, path),
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json'})
        try:
            response = self.browser.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            self.assertEqual(response.status, expected, content.decode(errors='replace')[:500])
            return content if raw else json.loads(content)

    def document(self, workspace, action, approved=True, expected=200):
        return self.request('/api/tools/call', {'tool': 'document', 'action': action,
            'workspace_id': workspace['id'], 'approval': {'approved': approved}}, expected)

    def test_deleted_project_and_context_archive_survive_daemon_and_h2_restart(self):
        credentials = {"username": "context_user", "password": "test-password-only"}
        self.request('/api/auth/register', credentials, 201)
        for n in range(18):
            self.request('/api/conversations/free', {'text': 'requirement-%s' % n}, 201)
        workspace = self.request('/api/workspaces', {'root': str(self.project), 'name': '可删除工程'}, 201)
        (self.project / 'keep.txt').write_text('preserved')
        service = self.request('/api/tools/call', {'tool': 'process', 'action': 'start',
            'workspace_id': workspace['id'], 'arguments': {'command': "python3 -c 'import time; time.sleep(30)'"},
            'approval': {'approved': True}})['data']
        path = '/api/workspaces/' + workspace['id'] + '/delete'
        body = {'confirmed': True, 'confirm_name': workspace['name']}
        self.request(path, body, 400)
        self.request('/api/tools/call', {'tool': 'process', 'action': 'stop',
            'workspace_id': workspace['id'], 'arguments': {'pid': service['pid']}})
        self.request(path, body)
        self.request('/api/auth/logout', {})
        self.cli('restart')
        self.request('/api/auth/login', credentials)
        self.assertEqual(self.request('/api/workspaces')['items'], [])
        self.assertEqual(len(self.request('/api/conversations')['items']), 18)
        self.assertEqual((self.project / 'keep.txt').read_text(), 'preserved')
        self.request('/api/workspaces/' + workspace['id'] + '/download', expected=404)
        self.assertEqual(self.request('/api/auth/me')['user']['balance'], 482)
        self.cli('stop')
        from backend.h2_store import H2Store
        store = H2Store(str(self.data / 'h2'))
        try:
            archives = store.read('conversation_archives', [])
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0]['archived_count'], 3)
            self.assertIn('requirement-0', archives[0]['summary'])
        finally:
            store.close()

    def test_logout_fresh_login_and_daemon_restart_preserve_all_saved_content(self):
        credentials = {'username': 'persistence_user', 'password': 'test-password-only'}
        user = self.request('/api/auth/register', credentials, 201)['user']
        free = self.request('/api/conversations/free', {'text': '记住这条持久化测试消息'}, 201)
        workspace = self.request('/api/workspaces', {'root': str(self.project), 'name': '持久工程',
            'description': '持久配置', 'start_command': 'python3 main.py'}, 201)
        task = self.request('/api/tasks', {'workspace_id': workspace['id'], 'goal': '创建示例代码',
            'patches': [{'path': 'main.py', 'content': 'def answer():\n    return 42\n'}]}, 201)
        self.request('/api/tasks/' + task['id'] + '/approve', {})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = self.request('/api/tasks/' + task['id'])['status']
            if status in ('succeeded', 'failed', 'cancelled'):
                break
            time.sleep(.1)
        self.assertEqual(status, 'succeeded')
        self.assertFalse(self.document(workspace, 'read')['data']['exists'])
        self.document(workspace, 'generate')
        # Restoring must read the actual saved file, not regenerate from symbols.
        document = '# 已保存的产物\n用户补充的内容也必须保留。\n'
        (self.project / 'CODESPIDER.md').write_text(document, encoding='utf-8')
        saved_bytes = {p: (self.project / p).read_bytes() for p in ('main.py', 'CODESPIDER.md')}
        events = self.request('/api/tasks/' + task['id'] + '/events')
        usage = self.request('/api/usage')
        balance = self.request('/api/auth/me')['user']['balance']
        original_instance = self.request('/api/health')['instance']
        for restart in (False, True):
            self.request('/api/auth/logout', {})
            for endpoint in ('/api/workspaces', '/api/conversations', '/api/tasks/' + task['id']):
                self.request(endpoint, expected=401)
            if restart:
                self.cli('restart')
                self.assertNotEqual(self.request('/api/health')['instance'], original_instance)
            # New cookie jar also models closing the browser / using another browser.
            self.browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            login = self.request('/api/auth/login', credentials)
            self.assertEqual(login['user']['id'], user['id'])
            self.assertEqual(login['user']['balance'], balance)
            self.assertEqual(self.request('/api/workspaces')['items'][0]['id'], workspace['id'])
            self.assertEqual(self.request('/api/workspaces')['items'][0]['description'], '持久配置')
            self.assertEqual(self.request('/api/workspaces')['items'][0]['start_command'], 'python3 main.py')
            free_history = self.request('/api/conversations')['items']
            self.assertEqual(free_history[0]['id'], free['id'])
            self.assertEqual(free_history[0]['reply'], free['reply'])
            history = self.request('/api/conversations?workspace_id=' + workspace['id'])['items']
            self.assertEqual(history[0]['task']['id'], task['id'])
            self.assertEqual(history[0]['status'], 'succeeded')
            self.assertEqual(history[0]['events'], events['items'])
            self.assertEqual(self.document(workspace, 'read', approved=False)['data']['content'], document)
            self.assertEqual(self.document(workspace, 'read')['data']['content'], document)
            tree = self.request('/api/workspaces/' + workspace['id'] + '/tree')['items']
            self.assertTrue({'main.py', 'CODESPIDER.md'} <= {entry['path'] for entry in tree})
            payload = self.request('/api/workspaces/' + workspace['id'] + '/download', raw=True)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                for name, content in saved_bytes.items():
                    self.assertEqual(archive.read(name), content)
                    self.assertEqual((self.project / name).read_bytes(), content)
            self.assertEqual(self.request('/api/usage'), usage, 'restore must not bill again')
        self.request('/api/auth/logout', {})
        self.request('/api/auth/register', {'username': 'another_user', 'password': 'test-password-only'}, 201)
        self.assertEqual(self.request('/api/conversations')['items'], [])
        self.request('/api/conversations?workspace_id=' + workspace['id'], expected=403)
        self.assertTrue((self.data / 'h2/accounts.mv.db').is_file())


if __name__ == '__main__':
    unittest.main()
