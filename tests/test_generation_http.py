import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, HTTPServer

from backend.app import AppContext, Handler
from tests.test_model_gateway import _ModelHandler
from tests.test_generation_workflow import turn


class GenerationHttpTests(unittest.TestCase):
    def test_remote_generation_reads_without_prompt_but_writes_only_after_approval(self):
        self.run_generation(False)

    def test_account_default_generates_without_thought_fields(self):
        self.run_generation(True)

    def run_generation(self, authenticated):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'project'; root.mkdir()
            context = AppContext(str(Path(temp)/'state'))
            class TestHandler(Handler):
                def log_message(self, *_args): pass
            TestHandler.context = context
            provider = HTTPServer(('127.0.0.1', 0), _ModelHandler)
            api = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
            for server in (provider, api):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                config = {'name': 'Real model', 'provider':'custom','model':'selected-test-model','base_url':'http://127.0.0.1:%s/v1'%provider.server_port,'api_key':'private-key'}
                context.auth_required = authenticated
                if authenticated:
                    configured_model = context.auth.create_model(config)
                else:
                    context.settings.update(config)
                workspace = context.workspaces.create(str(root))
                _ModelHandler.requests = []
                response_turn = turn([
                    {'path':'main.py','operation':'create','replacement':'answer = 42\n'},
                    {'path':'test_main.py','operation':'create','replacement':'import unittest\nfrom main import answer\nclass T(unittest.TestCase):\n def test_answer(self): self.assertEqual(answer,42)\n'}])
                if authenticated:
                    response_turn.pop('thinking')
                    response_turn.pop('steps')
                _ModelHandler.responses = [json.dumps(response_turn)]
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
                def post(path, body, status):
                    req=urllib.request.Request('http://127.0.0.1:%s%s'%(api.server_port,path), data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    try: response=opener.open(req,timeout=5)
                    except urllib.error.HTTPError as error: response=error
                    with response:
                        self.assertEqual(response.status,status)
                        return json.load(response)
                if authenticated:
                    post('/api/auth/register', {'username': 'admin', 'password': 'password123'}, 201)
                payload={'workspace_id':workspace.id,'goal':'Generate'}
                task=post('/api/tasks',payload,201)
                self.assertEqual(task['summary'], 'Generated')
                self.assertEqual(context.tasks.get(task['id']).summary, 'Generated')
                self.assertEqual(next(e.payload['summary'] for e in context.tasks.events(task['id']) if e.type == 'task.plan_ready'), 'Generated')
                if authenticated:
                    self.assertEqual(task['model_id'], configured_model['id'])
                    self.assertEqual(task['thinking'], [])
                    self.assertEqual(task['plan'], [])
                self.assertEqual(len(_ModelHandler.requests),1)
                self.assertEqual(_ModelHandler.requests[0]['model'],'selected-test-model')
                self.assertFalse((root/'main.py').exists())
                post('/api/tasks/%s/approve'%task['id'],{},200)
                context.tasks.executor.shutdown(wait=True)
                self.assertEqual(context.tasks.get(task['id']).status,'succeeded')
                self.assertEqual((root/'main.py').read_text(),'answer = 42\n')
                self.assertNotIn('private-key',json.dumps([e.to_dict() for e in context.tasks.events(task['id'])]))
            finally:
                for server in (api,provider): server.shutdown(); server.server_close()
                context.tasks.executor.shutdown(wait=True)
                context.processes.close();context.close()
