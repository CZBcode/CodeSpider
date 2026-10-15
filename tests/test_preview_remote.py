"""Opt-in real npm build through the independent Agent (also runs in bwrap)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import AppContext
from backend.tool_protocol import ToolRequest
from backend.previews import preview_asset
from tests.test_task_regressions import wait_until


@unittest.skipUnless(os.environ.get('CODESPIDER_RUN_PREVIEW_BUILD') == '1' and shutil.which('npm'), 'opt-in real npm preview integration')
class RemotePreviewTests(unittest.TestCase):
    def test_real_build_auto_update_failure_and_cancel_through_agent(self):
        with tempfile.TemporaryDirectory(prefix='preview-ipc-') as temp:
            base = Path(temp); root = base / 'project'; root.mkdir()
            data, socket = base / 'state', base / 'agent.sock'
            (root / 'package.json').write_text(json.dumps({'private':True, 'type':'module',
                'scripts':{'build':'vite build'}, 'dependencies':{'vue':'3.5.13','vite':'5.4.21'}}))
            (root / 'index.html').write_text('<div id="app"></div><script type="module" src="/main.js"></script>')
            (root / 'main.js').write_text("import {createApp,h} from 'vue';createApp({render:()=>h('h1','First remote preview')}).mount('#app');")
            token = 'preview-acceptance-only-token'
            with open(base / 'agent.log', 'w') as log:
                child = subprocess.Popen([sys.executable,'-m','agent_client.server','--data-dir',str(data),'--socket',str(socket)],
                    env=dict(os.environ,CODESPIDER_IPC_TOKEN=token),stdout=log,stderr=log)
                context = None
                try:
                    wait_until(socket.exists, timeout=10)
                    with patch.dict(os.environ, CODESPIDER_IPC_TOKEN=token): context = AppContext(str(data),str(socket))
                    workspace = context.workspaces.create(str(root), owner_id='alice')
                    def call(action, args=None):
                        response = context.tools.call(ToolRequest('preview',action,args or {},workspace_id=workspace.id,
                            owner_id='alice',approval={'approved':True}))
                        self.assertTrue(response.ok, response.error)
                        return response.data
                    def finished(): return call('status').get('job',{}).get('status') not in ('queued','installing','building')
                    call('build'); wait_until(finished,timeout=360)
                    first = call('status'); self.assertEqual(first['job']['status'],'published', first['job'])
                    self.assertIn(b'/preview/',preview_asset(context.store,context.workspaces,first['current']['id'],'')[1])
                    task = context.tasks.create(workspace.id,'update Vue', [{'path':'main.js','content':
                        "import {createApp,h} from 'vue';createApp({render:()=>h('h1','Updated remote preview')}).mount('#app');"}],owner_id='alice')
                    context.tasks.approve(task.id)
                    wait_until(lambda: context.tasks.get(task.id).status in ('succeeded','failed'),timeout=360)
                    self.assertEqual(context.tasks.get(task.id).status,'succeeded',context.tasks.get(task.id).error)
                    current = call('status')['current']; self.assertNotEqual(current['id'],first['current']['id'])
                    (root / 'main.js').write_text('broken syntax {{{')
                    call('build'); wait_until(finished,timeout=360)
                    status = call('status'); self.assertEqual(status['job']['status'],'failed')
                    self.assertEqual(status['current'],current)
                    package = json.loads((root / 'package.json').read_text()); package['scripts']['build']='node -e "setTimeout(()=>{},20000)"'
                    (root / 'package.json').write_text(json.dumps(package))
                    job = call('build')['job']
                    wait_until(lambda: call('status')['job']['status']=='building',timeout=360)
                    call('cancel',{'build_id':job['id']}); wait_until(finished,timeout=10)
                    self.assertEqual(call('status')['job']['status'],'cancelled')
                    self.assertEqual(call('status')['current'],current)
                finally:
                    if context:
                        context.tasks.executor.shutdown(wait=True); context.processes.close(); context.close()
                    child.terminate()
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
