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
    def test_remote_generation_requires_context_consent_and_executes_through_api(self):
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
                context.settings.update({'provider':'custom','model':'selected-test-model','base_url':'http://127.0.0.1:%s/v1'%provider.server_port,'api_key':'private-key'})
                workspace = context.workspaces.create(str(root))
                _ModelHandler.requests = []
                _ModelHandler.responses = [json.dumps(turn([
                    {'path':'main.py','operation':'create','replacement':'answer = 42\n'},
                    {'path':'test_main.py','operation':'create','replacement':'import unittest\nfrom main import answer\nclass T(unittest.TestCase):\n def test_answer(self): self.assertEqual(answer,42)\n'}]))]
                def post(path, body, status):
                    req=urllib.request.Request('http://127.0.0.1:%s%s'%(api.server_port,path), data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    try: response=urllib.request.urlopen(req,timeout=5)
                    except urllib.error.HTTPError as error: response=error
                    with response:
                        self.assertEqual(response.status,status)
                        return json.load(response)
                payload={'workspace_id':workspace.id,'goal':'Generate'}
                rejected=post('/api/tasks',payload,409)
                self.assertTrue(rejected['approval_required'])
                self.assertEqual(len(_ModelHandler.requests),0)
                task=post('/api/tasks',dict(payload,context_approved=True),201)
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
