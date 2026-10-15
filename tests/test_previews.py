import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from backend.app import AppContext
from backend.previews import preview_asset, PreviewService
from backend.tool_protocol import ToolRequest
from tests.test_task_regressions import wait_until
from tests import test_conversations


def vue_project(root):
    (root / 'package.json').write_text(json.dumps({'scripts': {'build': 'vite build'},
        'dependencies': {'vue': '^3.5.0'}, 'devDependencies': {'vite': '^5.4.0'}}))
    (root / 'index.html').write_text('<div id="app"></div><script type="module" src="/src/main.js"></script>')
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src/main.js').write_text("import {createApp} from 'vue'; createApp({template:'<h1>First preview</h1>'}).mount('#app');")


def fake_build(command, timeout=60, approved=False, cancel_event=None):
    match = re.search(r'--outDir=(\S+)', command)
    if match:
        root = Path(fake_build.root)
        output = root / match[1]; output.mkdir()
        (output / 'index.html').write_text('<h1>Built preview</h1>')
        (output / 'app.js').write_text('document.body.dataset.built="yes"')
    return {'exit_code': 0, 'output': 'build passed', 'risk': 'low'}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'; self.root.mkdir(); vue_project(self.root)
        self.context = AppContext(str(Path(self.temp.name) / 'state'))
        self.addCleanup(self.context.processes.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)
        self.workspace = self.context.workspaces.create(str(self.root), owner_id='alice')
        fake_build.root = str(self.root)

    def call(self, action, arguments=None, approved=True, owner='alice'):
        return self.context.tools.call(ToolRequest('preview', action, arguments or {},
            workspace_id=self.workspace.id, owner_id=owner, approval={'approved': approved}))

    def wait_build(self):
        wait_until(lambda: not self.context.tools.previews.workers, timeout=10)
        return self.call('status').data

    def test_permissions_success_persistence_and_failure_keep_last_good(self):
        self.assertEqual(self.call('build', approved=False).error['code'], 'APPROVAL_REQUIRED')
        self.assertEqual(self.call('status', owner='bob').error['code'], 'FORBIDDEN')
        self.assertFalse(self.call('status', approved=False).data.get('current'))
        with patch('backend.previews.AgentExecutor.run_command', side_effect=fake_build):
            self.assertTrue(self.call('build').ok)
            first = self.wait_build()
        self.assertEqual(first['job']['status'], 'published')
        self.assertIn(b'Built preview', preview_asset(self.context.store, self.context.workspaces, first['current']['id'], '')[1])
        reopened = PreviewService(self.context.store, self.context.workspaces, self.context.market)
        self.assertEqual(reopened.status(self.workspace)['current'], first['current'])
        with patch('backend.previews.AgentExecutor.run_command', return_value={'exit_code':1, 'output':'compiler error'}):
            self.assertTrue(self.call('build').ok)
            failed = self.wait_build()
        self.assertEqual(failed['job']['status'], 'failed')
        self.assertEqual(failed['current'], first['current'])

    def test_concurrent_build_cancel_and_no_publication(self):
        started = threading.Event()
        def block(command, timeout=60, approved=False, cancel_event=None):
            started.set(); cancel_event.wait(5)
            raise ValueError('cancelled')
        with patch('backend.previews.AgentExecutor.run_command', side_effect=block):
            build = self.call('build').data['job']['id']; self.assertTrue(started.wait(2))
            self.assertFalse(self.call('build').ok)
            self.assertTrue(self.call('cancel', {'build_id':build}).ok)
            status = self.wait_build()
        self.assertEqual(status['job']['status'], 'cancelled')
        self.assertFalse(status.get('current'))

    def test_source_race_and_symlink_output_rejected(self):
        def edit_during_build(*args, **kwargs):
            result = fake_build(*args, **kwargs)
            if '--outDir=' in args[0]:
                (self.root / 'src/main.js').write_text('changed during build')
            return result
        with patch('backend.previews.AgentExecutor.run_command', side_effect=edit_during_build):
            self.call('build'); status = self.wait_build()
        self.assertEqual(status['job']['status'], 'failed'); self.assertFalse(status.get('current'))
        def symlink(*args, **kwargs):
            result = fake_build(*args, **kwargs)
            match = re.search(r'--outDir=(\S+)', args[0])
            if match: (self.root / match[1] / 'secret').symlink_to(self.root / 'package.json')
            return result
        with patch('backend.previews.AgentExecutor.run_command', side_effect=symlink):
            self.call('build'); status = self.wait_build()
        self.assertEqual(status['job']['status'], 'failed'); self.assertIn('符号链接', status['job']['error'])

    def test_approved_task_automatically_builds_and_publishes(self):
        task = self.context.tasks.create(self.workspace.id, 'update vue',
            [{'path':'src/main.js', 'content':"export const version = 'updated';"}], owner_id='alice')
        with patch('backend.previews.AgentExecutor.run_command', side_effect=fake_build):
            self.context.tasks.approve(task.id)
            wait_until(lambda: self.context.tasks.get(task.id).status in ('succeeded','failed'), timeout=10)
        result = self.context.tasks.get(task.id)
        self.assertEqual(result.status, 'succeeded', result.error)
        events = self.context.tasks.events(task.id)
        self.assertIn('preview.published', [event.type for event in events])
        self.assertEqual(self.call('status').data['job']['task_id'], task.id)

    def test_readonly_task_does_not_publish(self):
        task = self.context.tasks.create(self.workspace.id, 'analyze vue', owner_id='alice')
        with patch('backend.previews.AgentExecutor.run_command', side_effect=fake_build):
            self.context.tasks.approve(task.id)
            wait_until(lambda: self.context.tasks.get(task.id).status in ('succeeded','failed'), timeout=10)
        self.assertNotIn('preview.published', [e.type for e in self.context.tasks.events(task.id)])
        self.assertFalse(self.call('status').data.get('job'))

    def test_changed_source_between_build_and_deploy_is_not_published(self):
        original = self.context.tools.previews.deploy
        def mutate_then_deploy(workspace, build_id, cancelled=None):
            (self.root / 'src/main.js').write_text('newer source')
            return original(workspace, build_id, cancelled)
        with patch('backend.previews.AgentExecutor.run_command', side_effect=fake_build), patch.object(self.context.tools.previews, 'deploy', side_effect=mutate_then_deploy):
            self.call('build'); status = self.wait_build()
        self.assertEqual(status['job']['status'], 'failed')
        self.assertIn('源码已变化', status['job']['error'])
        self.assertFalse(status.get('current'))


class PreviewHttpTests(unittest.TestCase):
    setUp = test_conversations.ConversationHttpTests.setUp
    tearDown = test_conversations.ConversationHttpTests.tearDown
    request = test_conversations.ConversationHttpTests.request

    def test_assets_isolation_traversal_and_deleted_project(self):
        vue_project(self.project); fake_build.root = str(self.project)
        body = {'tool':'preview', 'action':'build', 'workspace_id':self.workspace['id'], 'approval':{'approved':True}}
        self.request('/api/tools/call', body, 403, self.other)
        with patch('backend.previews.AgentExecutor.run_command', side_effect=fake_build):
            self.request('/api/tools/call', body)
            wait_until(lambda: not self.context.tools.previews.workers)
        result = self.request('/api/tools/call', dict(body, action='status'))['data']
        base = 'http://127.0.0.1:%s' % self.server.server_port
        url = base + result['current']['url']
        with urllib.request.urlopen(url) as response:
            self.assertIn(b'Built preview', response.read())
            self.assertIn('charset=utf-8', response.headers['Content-Type'])
            self.assertIn('sandbox allow-scripts allow-forms;', response.headers['Content-Security-Policy'])
            self.assertIn("form-action 'none'", response.headers['Content-Security-Policy'])
            self.assertNotIn('allow-same-origin', response.headers['Content-Security-Policy'])
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], '*')
        for suffix in ('%2e%2e/package.json', 'missing.js', '.env'):
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url + suffix)
            self.assertEqual(error.exception.code, 404)
        request = urllib.request.Request(base + '/api/auth/logout', data=b'{}', headers={'Origin':'null','Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as error: self.admin.open(request)
        self.assertEqual(error.exception.code, 403)
        self.request('/api/workspaces/'+self.workspace['id']+'/delete', {'confirm_name':self.workspace['name'],'confirmed':True})
        with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(url)
        self.assertEqual(error.exception.code, 404)
