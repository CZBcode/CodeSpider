import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from backend.app import AppContext, Handler
from backend.conversations import ConversationService
from backend.h2_store import H2Store, find_h2_jar
from backend.store import JsonStore


class ConversationTests(unittest.TestCase):
    def test_concurrent_saves_survive_reopening_and_remain_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            service = ConversationService(JsonStore(root), JsonStore(root))
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(lambda n: service.begin('alice', 'project', 'message %s' % n), range(30)))
            service.finish(ids[0], error='provider unavailable')
            service.begin('bob', 'project', 'private')
            service.begin('alice', 'different', 'other project')
            reopened = ConversationService(JsonStore(root), JsonStore(root))
            history = reopened.history('alice', 'project')
            self.assertEqual(len(history), 30)
            self.assertEqual(len({t['id'] for t in history}), 30)
            self.assertEqual(next(t for t in history if t['id'] == ids[0])['error'], 'provider unavailable')
            self.assertTrue(any(t['status'] == 'interrupted' for t in history))
            self.assertNotIn('private', json.dumps(history))

    @unittest.skipUnless(find_h2_jar(), 'H2 JDBC jar unavailable')
    def test_free_history_survives_h2_restart(self):
        with tempfile.TemporaryDirectory() as root:
            store = H2Store(str(Path(root)/'h2'))
            service = ConversationService(store, JsonStore(root))
            turn = service.begin('alice', '', '你好')
            service.finish(turn, reply='已保存')
            store.close()
            reopened = H2Store(str(Path(root)/'h2'))
            try:
                history = ConversationService(reopened, JsonStore(root)).history('alice', '')
                self.assertEqual(history[0]['reply'], '已保存')
                self.assertEqual(history[0]['status'], 'completed')
            finally:
                reopened.close()


class ConversationHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = AppContext(str(Path(self.temp.name)/'state'))
        self.context.auth_required = True
        class QuietHandler(Handler):
            def log_message(self, *_): pass
        QuietHandler.context = self.context
        self.handler = QuietHandler
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.admin = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self.other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self.request('/api/auth/register', {'username': 'admin', 'password': 'password123'}, 201)
        self.request('/api/auth/register', {'username': 'other', 'password': 'password123'}, 201, self.other)
        self.project = Path(self.temp.name)/'project'; self.project.mkdir()
        (self.project / 'README.md').write_text('download me', encoding='utf-8')
        self.workspace = self.request('/api/workspaces', {'root': str(self.project)}, 201)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.context.tasks.executor.shutdown(wait=True)
        self.context.processes.close(); self.context.close()
        self.temp.cleanup()

    def request(self, path, body=None, expected=200, opener=None):
        req = urllib.request.Request('http://127.0.0.1:%s%s' % (self.server.server_port, path),
            data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
        try: response = (opener or self.admin).open(req, timeout=10)
        except urllib.error.HTTPError as exc: response = exc
        with response:
            self.assertEqual(response.status, expected)
            return json.load(response)

    def history(self, opener=None):
        return self.request('/api/conversations?workspace_id='+self.workspace['id'], opener=opener)['items']

    def test_restore_finished_task_after_restart_without_execution_or_billing(self):
        task = self.request('/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'inspect project'}, 201)
        self.assertEqual(self.history()[0]['task']['id'], task['id'])
        self.request('/api/tasks/'+task['id']+'/approve', {})
        self.context.tasks.executor.shutdown(wait=True)
        before_usage = self.request('/api/auth/me')['usage']['total_calls']
        self.context.processes.close(); self.context.close()
        self.context = AppContext(str(Path(self.temp.name)/'state'))
        self.context.auth_required = True
        self.handler.context = self.context
        restored = self.history()
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]['goal'], 'inspect project')
        self.assertEqual(restored[0]['task']['status'], 'succeeded')
        self.assertEqual(restored[0]['task']['summary'], task['summary'])
        self.assertTrue(any(e['type']=='task.succeeded' for e in restored[0]['events']))
        self.assertEqual(self.request('/api/auth/me')['usage']['total_calls'], before_usage)
        self.assertEqual(self.history(self.other), [])
        for path in ('', '/events'):
            self.request('/api/tasks/'+task['id']+path, expected=403, opener=self.other)
        for action in ('approve', 'cancel'):
            self.request('/api/tasks/'+task['id']+'/'+action, {}, 403, self.other)

    def test_generation_is_saved_before_completion_and_errors_survive(self):
        entered = threading.Event(); release = threading.Event()
        def fail(*args, **kwargs):
            entered.set()
            release.wait(5)
            raise ValueError('provider temporarily unavailable')
        with patch.object(self.context.tasks.model, 'plan', side_effect=fail):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.request, '/api/tasks', {'workspace_id': self.workspace['id'], 'goal': 'generate'}, 400)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(self.history()[0]['status'], 'generating')
                finally: release.set()
                future.result()
        self.assertEqual(self.history()[0]['status'], 'failed')
        self.assertEqual(self.history()[0]['error'], 'provider temporarily unavailable')
        self.assertNotIn('task', self.history()[0])

    def test_free_chat_is_saved_and_authentication_is_required(self):
        reply = self.request('/api/conversations/free', {'text': 'hello <script>'}, 201)
        history = self.request('/api/conversations')['items']
        self.assertEqual(history[0]['goal'], 'hello <script>')
        self.assertEqual(history[0]['reply'], reply['reply'])
        self.assertIn('hello <script>', reply['reply'])
        self.assertEqual(self.request('/api/auth/me')['user']['balance'], 499)
        self.assertEqual(self.request('/api/conversations', opener=self.other)['items'], [])
        self.request('/api/conversations', expected=401, opener=urllib.request.build_opener())
        self.request('/api/conversations/free', {'text': ''}, 400)

    def test_project_download_returns_a_zip_without_dependencies_or_git(self):
        response = self.admin.open(urllib.request.Request(
            'http://127.0.0.1:%s/api/workspaces/%s/download' % (self.server.server_port, self.workspace['id'])))
        with response:
            payload = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'application/zip')
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(archive.namelist(), ['README.md'])
            self.assertEqual(archive.read('README.md'), b'download me')
