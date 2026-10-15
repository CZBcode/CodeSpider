import json
import os
from unittest.mock import patch
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from backend.app import AppContext, Handler
from backend.h2_store import find_h2_jar
from http.server import ThreadingHTTPServer


@unittest.skipUnless(find_h2_jar(), "H2 JDBC jar unavailable")
class UserIsolationAndMarketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        expanduser = os.path.expanduser
        home = patch('backend.workspaces.os.path.expanduser', side_effect=lambda value:
            str(Path(self.temp.name)/'projects') if value == '~/.codespider/project' else expanduser(value))
        home.start(); self.addCleanup(home.stop)
        with patch.dict(os.environ, CODESPIDER_AUTH_REQUIRED="1"):
            self.context = AppContext(str(Path(self.temp.name) / "state"))
        class QuietHandler(Handler):
            def log_message(self, *_): pass
        QuietHandler.context = self.context
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.alice = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self.bob = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self.request("/api/auth/register", {"username": "alice", "password": "password123"}, 201, self.alice)
        bob = self.request("/api/auth/register", {"username": "bob", "password": "password123"}, 201, self.bob)
        self.context.auth.assign_model(bob["user"]["id"], "mdl_local")

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.context.tasks.executor.shutdown(wait=True)
        self.context.processes.close(); self.context.close(); self.temp.cleanup()

    def request(self, path, body=None, expected=200, opener=None):
        req = urllib.request.Request("http://127.0.0.1:%s%s" % (self.server.server_port, path),
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            response = (opener or self.alice).open(req, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = json.load(response)
            self.assertEqual(response.status, expected, payload)
            return payload

    def test_projects_tools_tasks_and_market_are_user_scoped(self):
        root = Path(self.temp.name) / "alice-project"; root.mkdir()
        workspace = self.request("/api/workspaces", {"root": str(root), "name": "Alice"}, 201, self.alice)
        self.assertEqual(self.request("/api/workspaces", opener=self.bob)["items"], [])
        self.request("/api/workspaces/%s/tree" % workspace["id"], expected=403, opener=self.bob)
        self.request("/api/conversations?workspace_id=%s" % workspace["id"], expected=403, opener=self.bob)
        self.request("/api/tasks", {"workspace_id": workspace["id"], "goal": "偷看项目"}, expected=403, opener=self.bob)
        self.request("/api/tools/call", {"tool": "workspace", "action": "list_tree", "workspace_id": workspace["id"]}, expected=403, opener=self.bob)
        self.request("/api/workspaces/%s/settings" % workspace["id"], dict(workspace), expected=403, opener=self.bob)
        self.request("/api/workspaces/%s/download" % workspace["id"], expected=403, opener=self.bob)

        market = self.request("/api/market", opener=self.alice)
        self.assertTrue({"plugin.python", "plugin.springboot", "plugin.vue"} <= {x["id"] for x in market["plugins"]})
        self.request("/api/market/preferences", {"item_id": "plugin.python", "enabled": False}, opener=self.alice)
        alice_market = self.request("/api/market", opener=self.alice)
        bob_market = self.request("/api/market", opener=self.bob)
        self.assertFalse(next(x for x in alice_market["plugins"] if x["id"] == "plugin.python")["enabled"])
        self.assertTrue(next(x for x in bob_market["plugins"] if x["id"] == "plugin.python")["enabled"])
        skill = self.request("/api/market/skills", {"name": "Alice API", "keywords": ["api"], "description": "private", "instructions": "Use Alice API rules."}, 201, self.alice)
        self.assertIn(skill["id"], {x["id"] for x in self.request("/api/market", opener=self.alice)["skills"]})
        self.assertNotIn(skill["id"], {x["id"] for x in self.request("/api/market", opener=self.bob)["skills"]})

        self.request("/api/tasks", {"workspace_id": workspace["id"], "goal": "Python 函数测试"}, expected=400, opener=self.alice)
        self.request("/api/market/preferences", {"item_id": "plugin.python", "enabled": True}, opener=self.alice)
        task = self.request("/api/tasks", {"workspace_id": workspace["id"], "goal": "Python 函数测试", "patches": [{"path": "main.py", "content": "answer = 42\n"}]}, 201, self.alice)
        self.assertEqual(task["owner_id"], self.request("/api/auth/me", opener=self.alice)["user"]["id"])
        self.assertEqual(task["plugin_id"], "plugin.python")
        self.request("/api/tasks/%s" % task["id"], expected=403, opener=self.bob)

    def test_concurrent_free_chats_are_scoped_by_account(self):
        from concurrent.futures import ThreadPoolExecutor
        def send(pair):
            opener, text = pair
            return self.request("/api/conversations/free", {"text": text}, 201, opener)["reply"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(send, [(self.alice, "alice only"), (self.bob, "bob only")]))
        self.assertIn("alice only", replies[0]); self.assertIn("bob only", replies[1])
        self.assertIn("alice only", json.dumps(self.request("/api/conversations", opener=self.alice), ensure_ascii=False))
        self.assertNotIn("bob only", json.dumps(self.request("/api/conversations", opener=self.alice), ensure_ascii=False))
        self.assertIn("bob only", json.dumps(self.request("/api/conversations", opener=self.bob), ensure_ascii=False))
        self.assertNotIn("alice only", json.dumps(self.request("/api/conversations", opener=self.bob), ensure_ascii=False))

    def test_raw_tool_task_spoof_memory_and_path_boundaries(self):
        a = self.request('/api/workspaces', {'name':'same-name'}, 201, self.alice)
        b = self.request('/api/workspaces', {'name':'same-name'}, 201, self.bob)
        self.assertNotEqual(a['root'], b['root'])
        Path(a['root'], 'secret.txt').write_text('alice private')
        task = self.request('/api/tasks', {'workspace_id':a['id'],'goal':'inspect'}, 201)
        for tool, action, arguments in [('workspace','read_file',{'path':'secret.txt'}),
                                         ('document','read',{}),('process','cancel',{})]:
            self.request('/api/tools/call', {'tool':tool,'action':action,'workspace_id':a['id'],
                'task_id':task['id'], 'owner_id':a['owner_id'], 'approval':{'approved':True},
                'arguments':arguments},403,self.bob)
        self.assertEqual(self.context.tasks.get(task['id']).status,'created')
        self.request('/api/tools/call',{'tool':'process','action':'stop','arguments':{'pid':1}},403,self.bob)
        for root in [a['root'], str(Path(a['root']).parent), str(Path(a['root'])/'sub')]:
            Path(root).mkdir(exist_ok=True)
            self.request('/api/workspaces',{'root':root},403,self.bob)
        self.request('/api/workspaces',{'root':b['root']},403,self.alice)
        self.request('/api/workspaces',{'root':self.context.store.root},403,self.alice)
        link = Path(b['root'])/'other'; link.symlink_to(a['root'], target_is_directory=True)
        self.request('/api/tools/call',{'tool':'workspace','action':'read_file','workspace_id':b['id'],
            'approval':{'approved':True},'arguments':{'path':'other/secret.txt'}},400,self.bob)
        for opener, marker in [(self.alice,'alice-private'),(self.bob,'bob-private')]:
            self.request('/api/memories',{'type':'preference','scope_id':'global','content':{'marker':marker}},201,opener)
        data=self.request('/api/memories/search?q=private&scope_id=global',opener=self.bob)
        self.assertIn('bob-private',json.dumps(data)); self.assertNotIn('alice-private',json.dumps(data))

    def test_safe_read_tools_do_not_prompt_but_ownership_and_mutations_remain_guarded(self):
        workspace=self.request('/api/workspaces',{'name':'safe-reads'},201,self.alice)
        root=Path(workspace['root'])
        (root/'main.py').write_text('def answer():\n    return 42\n')
        (root/'CODESPIDER.md').write_text('# saved document')
        operations=[('workspace','list_tree',{}),('workspace','read_file',{'path':'main.py'}),
                    ('workspace','search',{'query':'answer'}),('code','symbols',{}),
                    ('code','index',{}),('code','detect',{}),('code','context',{}),
                    ('code','design_review',{}),('document','read',{}),('process','list',{})]
        for tool,action,arguments in operations:
            with self.subTest(tool=tool,action=action):
                payload={'tool':tool,'action':action,'workspace_id':workspace['id'],'arguments':arguments}
                self.assertTrue(self.request('/api/tools/call',payload,200,self.alice)['ok'])
                self.request('/api/tools/call',payload,403,self.bob)
        for tool,action,args,status in [
            ('workspace','write_file',{'path':'main.py','content':'overwrite'},400),
            ('workspace','read_file',{'path':'../outside.txt'},400),
            ('document','generate',{},409),
            ('process','run',{'command':'python3 --version'},409)]:
            self.request('/api/tools/call',{'tool':tool,'action':action,'workspace_id':workspace['id'],'arguments':args},status)
        self.assertEqual((root/'main.py').read_text(),'def answer():\n    return 42\n')
        self.assertEqual((root/'CODESPIDER.md').read_text(),'# saved document')

    def test_function_market_executes_with_approval_and_user_installation(self):
        a=self.request('/api/workspaces',{'name':'functions'},201)
        Path(a['root'],'readme.txt').write_text('persisted function output')
        request={'tool':'function','action':'call','workspace_id':a['id'],
            'arguments':{'function_id':'function.workspace.read','input':{'path':'readme.txt'}}}
        self.assertEqual(self.request('/api/tools/call',request)['data']['content'],'persisted function output')
        self.request('/api/tools/call',request,403,self.bob)
        self.request('/api/market/preferences',{'item_id':'function.workspace.read','enabled':False,'installed':False})
        self.request('/api/tools/call',request,400)
        self.request('/api/market/preferences',{'item_id':'function.workspace.read','enabled':True,'installed':True})
        request['arguments']['input']['owner_id']=a['owner_id']
        self.request('/api/tools/call',request,400)
        skill=self.request('/api/market/skills',{'name':'private','instructions':'Keep contracts','keywords':['contracts']},201)
        self.request('/api/market/preferences',{'item_id':skill['id'],'enabled':False})
        self.request('/api/market/preferences',{'item_id':skill['id'],'enabled':True},400,self.bob)
        self.request('/api/market/preferences',{'item_id':'plugin.vue','enabled':'false'},400)
        self.request('/api/market/skills',{'name':'bad','instructions':'rules','keywords':'wrong'},400)

    def test_overlapping_project_generations_keep_context_models_outputs_and_billing_separate(self):
        from concurrent.futures import ThreadPoolExecutor
        a=self.request('/api/workspaces',{'name':'alice-gen'},201)
        b=self.request('/api/workspaces',{'name':'bob-gen'},201,self.bob)
        for workspace in [a,b]:
            Path(workspace['root'],'README.md').write_text(workspace['name'])
        ma=self.context.auth.create_model({'name':'A','provider':'custom','model':'model-a','base_url':'http://provider-a','api_key':'test-key-a'})
        mb=self.context.auth.create_model({'name':'B','provider':'custom','model':'model-b','base_url':'http://provider-b','api_key':'test-key-b'})
        self.context.auth.assign_model(b['owner_id'],mb['id'])
        self.request('/api/models/select',{'model_id':ma['id']})
        self.request('/api/models/select',{'model_id':mb['id']},opener=self.bob)
        barrier=threading.Barrier(2); observed={}
        def plan(goal,context,settings_override=None):
            observed[goal]=(context,dict(settings_override))
            barrier.wait(timeout=10)
            return {'schema':'agent.turn/v1','summary':goal+' reply','patches':[
                {'path':'main.py','operation':'create','replacement':'value = '+repr(goal)+'\n'}]}
        def generate(pair):
            workspace,opener,goal=pair
            return self.request('/api/tasks',{'workspace_id':workspace['id'],'goal':goal,'context_approved':True},201,opener)
        with patch.object(self.context.tasks.model,'plan',side_effect=plan):
            with ThreadPoolExecutor(max_workers=2) as pool:
                ta,tb=list(pool.map(generate,[(a,self.alice,'Python alice'),(b,self.bob,'Python bob')]))
        self.assertEqual(observed['Python alice'][1]['model'],'model-a')
        self.assertEqual(observed['Python bob'][1]['model'],'model-b')
        self.assertNotIn('bob-gen',json.dumps(observed['Python alice'][0]))
        self.assertNotIn('alice-gen',json.dumps(observed['Python bob'][0]))
        for workspace,opener,task,other in [(a,self.alice,ta,'Python bob'),(b,self.bob,tb,'Python alice')]:
            self.request('/api/tasks/'+task['id']+'/approve',{},opener=opener)
            history=self.request('/api/conversations?workspace_id='+workspace['id'],opener=opener)
            self.assertNotIn(other,json.dumps(history))
            self.assertEqual(self.request('/api/usage',opener=opener)['total_calls'],1)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(Path(a['root'],'main.py').read_text(),"value = 'Python alice'\n")
        self.assertEqual(Path(b['root'],'main.py').read_text(),"value = 'Python bob'\n")
        self.assertEqual(self.context.tasks.get(ta['id']).status,'succeeded')
        self.assertEqual(self.context.tasks.get(tb['id']).status,'succeeded')


if __name__ == "__main__":
    unittest.main()
