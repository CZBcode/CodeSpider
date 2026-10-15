import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agent_client.executor import AgentExecutor
from backend.app import AppContext
from backend.policy import WorkspacePolicy
from backend.tool_protocol import ToolRequest
from engineering_plugins import prototype
from engineering_plugins.registry import detect
from tests.test_task_regressions import wait_until


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'; self.root.mkdir()
        self.context = AppContext(str(Path(self.temp.name) / 'state'))
        self.addCleanup(self.context.close)
        self.addCleanup(self.context.processes.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)

    def files(self, **values):
        for name, value in values.items():
            (self.root / name).write_text(value)

    def test_semantic_recommendation_and_existing_stack_isolation(self):
        for text in ('做一个前端原型，用 Element UI 表格', 'HTML JS CSS 仪表盘', '静态页面原型', 'build an html prototype',
                     '不用 Vue，用 HTML 开发页面', 'build an HTML prototype without Vue'):
            selected = self.context.market.select(text, owner_id='alice')
            self.assertEqual(selected['plugin']['id'], 'plugin.prototype', text)
            self.assertFalse(selected['requires_choice'], text)
        self.assertEqual(self.context.market.select('Vue 管理页面')['plugin']['id'], 'plugin.vue')
        self.assertEqual(self.context.market.select('javascript 前端组件')['plugin']['id'], 'plugin.vue')
        self.assertEqual(self.context.market.select('增加 HTML 原型', 'vue')['plugin']['id'], 'plugin.vue')
        self.assertTrue(self.context.market.select('Vue 工程或者 HTML 原型')['requires_choice'])
        self.context.market.set_enabled('alice', 'plugin.prototype', False)
        with self.assertRaises(ValueError): self.context.market.select('HTML 原型', owner_id='alice')
        self.assertEqual(self.context.market.select('HTML 原型', owner_id='bob')['plugin']['id'], 'plugin.prototype')

    def test_detection_does_not_capture_existing_frameworks(self):
        self.files(**{'index.html':'<h1>Prototype</h1>'})
        self.assertEqual(detect(str(self.root))['type'], 'html-prototype')
        self.files(**{'package.json':json.dumps({'dependencies':{'vue':'3'}})})
        self.assertEqual(detect(str(self.root))['type'], 'vue')
        (self.root / 'package.json').unlink()
        self.files(**{'pom.xml':'<project/>'})
        self.assertEqual(detect(str(self.root))['type'], 'java-springboot')
        (self.root / 'pom.xml').unlink()
        self.files(**{'main.py':'value = 1'})
        self.assertEqual(detect(str(self.root))['type'], 'python')

    def test_short_new_prototype_uses_file_batches_but_existing_edits_stay_fast(self):
        settings = {'provider':'custom','model':'fake','base_url':'https://example.invalid/v1','api_key':'test-only'}
        workspace = self.context.workspaces.create(str(self.root), owner_id='alice')
        turn = self.context.tasks.model.validate_turn({'summary':'页面草稿', 'patches':[
            {'path':'index.html','operation':'create','replacement':'<h1>成员</h1>'}]})
        with patch('backend.project_generator.ProjectGenerator.generate', return_value=turn) as staged, \
             patch.object(self.context.tasks.model, 'plan', return_value=turn) as single:
            task = self.context.tasks.create(workspace.id, 'HTML 原型', model_settings=settings,
                owner_id='alice', background_generation=True)
            staged.assert_called_once()
            single.assert_not_called()
            self.assertEqual(task.plugin_id, 'plugin.prototype')
            self.assertFalse((self.root/'index.html').exists(), 'Generation must remain a proposal until approval')

        self.files(**{'index.html':'<h1>成员</h1>'})
        existing = self.context.workspaces.create(str(self.root), owner_id='alice')
        edit = self.context.tasks.model.validate_turn({'summary':'改标题', 'patches':[
            {'path':'index.html','operation':'apply_patch','expected':'<h1>成员</h1>','replacement':'<h1>团队成员</h1>'}]})
        with patch('backend.project_generator.ProjectGenerator.generate') as staged, \
             patch.object(self.context.tasks.model, 'plan', return_value=edit) as single:
            self.context.tasks.create(existing.id, '改标题', model_settings=settings,
                owner_id='alice', background_generation=True)
            staged.assert_not_called()
            single.assert_called_once()

    def test_bundled_assets_are_complete_and_user_files_are_not_overwritten(self):
        self.files(**{'index.html':'<script src="vendor/codespider/vue.min.js"></script>'})
        policy = WorkspacePolicy(str(self.root)); prototype.prepare_assets(policy)
        self.assertTrue((self.root/'vendor/codespider/fonts/element-icons.woff').is_file())
        prototype.prepare_assets(policy)
        library = self.root/'vendor/codespider/vue.min.js'; library.write_text('custom version')
        with self.assertRaisesRegex(ValueError, '保留路径'): prototype.prepare_assets(policy)
        self.assertEqual(library.read_text(), 'custom version')
        self.assertTrue(policy.is_ignored('vendor/codespider/vue.min.js'))
        self.assertFalse(policy.is_ignored('vendor/codespider-custom/app.js'))

    @unittest.skipUnless(shutil.which('node'), 'Node required for JS syntax checking')
    def test_verifier_catches_missing_assets_bad_js_and_cdn(self):
        executor = AgentExecutor(WorkspacePolicy(str(self.root)))
        command = prototype.verification(str(self.root))['verify_command']
        self.files(**{'index.html':'<link rel="stylesheet" href="styles.css"><script src="app.js"></script>',
                      'styles.css':'body{color:red}', 'app.js':'function add(a,b){return a+b;}'} )
        self.assertEqual(executor.run_command(command, approved=True)['exit_code'], 0)
        self.files(**{'app.js':'function broken( {'})
        self.assertNotEqual(executor.run_command(command, approved=True)['exit_code'], 0)
        self.files(**{'app.js':'const value = 1;', 'index.html':'<img src="missing.png">'})
        self.assertIn('缺失', executor.run_command(command, approved=True)['output'])
        self.files(**{'index.html':'<script src="https://unpkg.com/vue"></script>'})
        self.assertIn('外部或根目录', executor.run_command(command, approved=True)['output'])
        self.files(**{'index.html':'<script type="module">import {x} from "./missing.js";</script>'})
        self.assertIn('缺失', executor.run_command(command, approved=True)['output'])

    @unittest.skipUnless(shutil.which('node'), 'Node required for JS syntax checking')
    def test_approved_prototype_task_publishes_without_npm_and_failure_preserves_it(self):
        workspace = self.context.workspaces.create(str(self.root), owner_id='alice')
        patches = [{'path':'index.html','content':'<h1>Plain prototype</h1><script src="app.js"></script>'},
                   {'path':'app.js','content':'function add(a,b){return a+b;}'}]
        task = self.context.tasks.create(workspace.id, '开发 HTML 前端原型', patches, owner_id='alice')
        self.assertEqual(task.plugin_id, 'plugin.prototype')
        self.context.tasks.approve(task.id)
        wait_until(lambda:self.context.tasks.get(task.id).status in ('failed','succeeded'),timeout=15)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded', self.context.tasks.get(task.id).error)
        status = lambda:self.context.tools.call(ToolRequest('preview','status',workspace_id=workspace.id,owner_id='alice')).data
        current = status()['current']; self.assertTrue(current)
        self.assertFalse((self.root / 'package.json').exists()); self.assertFalse((self.root / 'node_modules').exists())
        task = self.context.tasks.create(workspace.id, '修改原型', [{'path':'app.js','content':'broken {{{'}],owner_id='alice')
        self.context.tasks.approve(task.id)
        wait_until(lambda:self.context.tasks.get(task.id).status in ('failed','succeeded'),timeout=15)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        self.assertEqual(status()['current'],current)
