import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from backend.market import MarketService
from backend.store import JsonStore
from backend.workspaces import WorkspaceManager
from code_intelligence.adapters import detect_project
from engineering_plugins.registry import plugins


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.market=MarketService(JsonStore(str(self.root/'state')))

    def test_semantic_selection_and_installation_are_account_scoped(self):
        for goal, expected in [('实现 Python 账单模块','plugin.python'),('生成 Vue 商品列表','plugin.vue'),
                                ('用 Spring Boot 做订单接口','plugin.springboot'),('javascript 前端组件','plugin.vue')]:
            selected=self.market.select(goal,owner_id='alice')
            self.assertEqual(selected['plugin']['id'],expected)
            self.assertEqual(selected['selection'],'semantic')
            self.assertTrue(selected['plugin']['instructions'])
        self.assertIsNone(self.market.select('copy this text')['plugin'])
        self.assertEqual(self.market.select('修改接口','python')['selection'],'project_type')
        ambiguous=self.market.select('Python Vue')
        self.assertTrue(ambiguous['requires_choice'])
        self.assertTrue(ambiguous['recommendation'])
        self.assertEqual(len(ambiguous['alternatives']),4)
        self.market.set_enabled('alice','plugin.python',False,False)
        with self.assertRaises(ValueError): self.market.select('Python 工程',owner_id='alice')
        with self.assertRaises(ValueError): self.market.select('修改工程','python','alice')
        self.assertEqual(self.market.select('Python 工程',owner_id='bob')['plugin']['id'],'plugin.python')
        reopened=MarketService(JsonStore(str(self.root/'state')))
        self.assertFalse(reopened.by_id('plugin.python','alice')['installed'])
        self.market.set_enabled('alice','plugin.python',True,True)
        self.assertTrue(reopened.by_id('plugin.python','alice')['enabled'])

    def test_plugins_supply_detection_setup_tests_and_versioned_guidance(self):
        self.assertEqual(len(plugins()),4)
        cases=[('python',{'main.py':'def f(): return 42','tests/test_main.py':'import unittest'},'python3 -m compileall -q .'),
               ('java-springboot',{'pom.xml':'<project/>'},'mvn -q test'),
               ('vue',{'package.json':json.dumps({'dependencies':{'vue':'3'},'scripts':{'test':'vitest'}}), 'package-lock.json':'{}'},'npm run build')]
        for project_type,files,command in cases:
            root=self.root/project_type;root.mkdir()
            for name,content in files.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
            result=detect_project(str(root))
            self.assertEqual(result['type'],project_type)
            self.assertEqual(result['verify_command'],command)
            if project_type=='python': self.assertIn('python3 -m unittest discover -s tests -v',result['verification_commands'])
            if project_type=='vue': self.assertEqual(result['setup_commands'],['npm ci --ignore-scripts --no-audit --no-fund'])
        gradle=self.root/'gradle';gradle.mkdir();(gradle/'build.gradle').write_text('plugins {}');(gradle/'gradlew').touch()
        self.assertEqual(detect_project(str(gradle))['verify_command'],'./gradlew test')

    def test_personal_skills_are_selected_only_for_their_owner(self):
        skill=self.market.add_skill('alice',{'name':'Alice contracts','instructions':'Use contract v3','keywords':['billing']})
        self.assertIn(skill['id'],{s['id'] for s in self.market.select('billing module',owner_id='alice')['skills']})
        self.assertNotIn(skill['id'],{s['id'] for s in self.market.select('billing module',owner_id='bob')['skills']})
        self.market.set_enabled('alice',skill['id'],False)
        self.assertNotIn(skill['id'],{s['id'] for s in self.market.select('billing module',owner_id='alice')['skills']})

    def test_concurrent_registration_and_old_task_roots_cannot_cross_owners(self):
        manager=WorkspaceManager(self.market.store)
        root=self.root/'shared';root.mkdir()
        def register(owner):
            try:return manager.create(str(root),owner_id=owner)
            except PermissionError:return None
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(register,['alice','bob']))
        winner=next(x for x in results if x)
        self.assertEqual(sum(x is not None for x in results),1)
        loser='bob' if winner.owner_id=='alice' else 'alice'
        self.market.store.append('tasks',{'id':'old','owner_id':winner.owner_id,'workspace_id':winner.id,'workspace_snapshot':winner.to_dict()})
        other=self.root/'new';other.mkdir()
        manager.update(winner.id,'new',str(other),'','',owner_id=winner.owner_id)
        with self.assertRaises(PermissionError): manager.create(str(root),owner_id=loser)

    def test_legacy_ownership_migration_is_idempotent_and_preserves_snapshots(self):
        manager=WorkspaceManager(self.market.store)
        root=self.root/'legacy';root.mkdir()
        workspace=manager.create(str(root))
        self.market.store.append('tasks',{'id':'legacy-task','owner_id':'alice','workspace_id':workspace.id,'workspace_snapshot':workspace.to_dict()})
        self.assertEqual(manager.migrate_legacy_ownership('admin'),1)
        self.assertEqual(manager.migrate_legacy_ownership('admin'),0)
        self.assertEqual(manager.get(workspace.id,owner_id='alice').owner_id,'alice')
        self.assertEqual(manager.get(workspace.id,'legacy-task','alice').owner_id,'alice')
        with self.assertRaises(PermissionError): manager.get(workspace.id,owner_id='bob')
        self.assertEqual(self.market.store.read('tasks',[])[0]['workspace_snapshot']['root'],str(root.resolve()))

    def test_new_plugin_is_discovered_through_registry_without_core_type_switch(self):
        from types import SimpleNamespace
        extra=SimpleNamespace(MANIFEST={'id':'plugin.example','kind':'plugin','version':'1.0.0','name':'Example',
            'project_types':['example'],'keywords':['example-lang'],'instructions':'Example rules'},
            detect=lambda root:(Path(root)/'example.toml').exists(),
            verification=lambda root:{'verify_command':'example test','commands':['example test']})
        with patch('engineering_plugins.registry.plugins',return_value=(extra,)), patch('backend.market.plugins',return_value=(extra,)):
            (self.root/'example.toml').touch()
            self.assertEqual(detect_project(str(self.root))['type'],'example')
            self.assertEqual(self.market.select('example-lang project')['plugin']['id'],'plugin.example')
