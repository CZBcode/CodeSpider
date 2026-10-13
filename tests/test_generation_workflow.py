import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import AppContext
from backend.model_gateway import ModelGateway, ModelContractError, MAX_ITEM_CHARS
from backend.policy import ApprovalRequired
from backend.tool_protocol import ToolRequest
from code_intelligence.adapters import detect_project


def turn(patches):
    return {'schema':'agent.turn/v1', 'summary':'Generated', 'thinking':['Brief implementation summary'],
            'steps':['Read','Implement','Test','Report'], 'tool_calls':[], 'patches':patches}


class GenerationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        self.context = AppContext(str(Path(self.temp.name)/'state'))
        self.addCleanup(self.context.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)
        self.workspace = self.context.workspaces.create(str(self.root))
        self.remote = {'provider':'custom','base_url':'http://unused.invalid','model':'test','api_key':'test'}

    def test_context_requires_approval_before_model_call(self):
        with patch.object(self.context.tasks.model, 'plan') as model:
            with self.assertRaises(ApprovalRequired):
                self.context.tasks.create(self.workspace.id, 'generate', model_settings=self.remote)
            model.assert_not_called()

    def test_existing_source_and_ast_reach_model_and_edits_keep_full_plan(self):
        old = 'def total():\n    return 0\n'
        (self.root/'main.py').write_text(old)
        (self.root/'.env').write_text('API_KEY=private')
        (self.root/'credentials.json').write_text('{"key":"private"}')
        (self.root/'node_modules').mkdir()
        (self.root/'node_modules/vendor.js').write_text('private')
        self.context.workspaces.update(self.workspace.id, 'example', str(self.root), '', 'Python 3.9 contract')
        response = turn([{'path':'main.py','operation':'apply_patch','expected':old,'replacement':old.replace('0','42')}])
        with patch.object(self.context.tasks.model, 'plan', return_value=response) as model:
            task = self.context.tasks.create(self.workspace.id, 'fix total', model_settings=self.remote, context_approved=True)
            sent = model.call_args.args[1]
            self.assertEqual(sent['files'], {'main.py':old})
            self.assertEqual(sent['symbols'][0]['name'], 'total')
            self.assertEqual(sent['structure']['modules'][0]['symbols'][0]['name'], 'total')
            self.assertEqual(sent['structure']['modules'][0]['parser'], 'python-ast')
            self.assertEqual(sent['description'], 'Python 3.9 contract')
            self.assertEqual(len(task.plan), 4)
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        self.assertIn('return 42', (self.root/'main.py').read_text())

    def test_empty_generation_is_rejected_not_reported_as_success(self):
        with patch.object(self.context.tasks.model, 'plan', return_value=turn([])):
            with self.assertRaisesRegex(ModelContractError, 'no code patches'):
                self.context.tasks.create(self.workspace.id, 'generate', model_settings=self.remote, context_approved=True)
        self.assertEqual(self.context.tasks._tasks(), [])

    def test_generated_tests_are_actually_executed(self):
        task = self.context.tasks.create(self.workspace.id, 'generate', patches=[
            {'path':'main.py','content':'value = 1\n'},
            {'path':'test_main.py','content':'import unittest\nfrom main import value\nclass T(unittest.TestCase):\n def test_value(self): self.assertEqual(value, 2)\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        outputs = [e.payload for e in self.context.tasks.events(task.id) if e.type == 'process.output']
        self.assertEqual(outputs[0]['exit_code'], 0)  # Compiles successfully.
        self.assertEqual(outputs[-1]['exit_code'], 1)  # Behaviour fails.
        self.assertIn('unittest', outputs[-1]['command'])

    def test_create_file_does_not_overwrite_a_file_added_after_approval_preview(self):
        task = self.context.tasks.create(self.workspace.id, 'create', patches=[{'path':'main.py','operation':'create','replacement':'generated=1\n'}])
        (self.root/'main.py').write_text('user_change=1\n')
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        self.assertEqual((self.root/'main.py').read_text(), 'user_change=1\n')

    def test_explicit_create_with_empty_expected_remains_a_create(self):
        task = self.context.tasks.create(self.workspace.id, 'create', patches=[
            {'path':'main.py','operation':'create','expected':'','replacement':'answer=42\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        self.assertEqual((self.root/'main.py').read_text(), 'answer=42\n')

    def test_zero_discovered_tests_is_not_reported_as_test_success(self):
        task = self.context.tasks.create(self.workspace.id, 'generate', patches=[
            {'path':'main.py','content':'value = 1\n'},
            {'path':'test_main.py','content':'def test_value():\n    assert False\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        self.assertIn('没有执行任何', self.context.tasks.get(task.id).error)

    def test_partial_node_modules_does_not_skip_dependency_install(self):
        (self.root/'package.json').write_text(json.dumps({'dependencies':{'vue':'3.4.21'},'scripts':{'test':'vitest run'}}))
        (self.root/'node_modules').mkdir()
        self.assertIn('npm install', detect_project(str(self.root))['setup_commands'][0])
        (self.root/'package-lock.json').write_text('{}')
        self.assertIn('npm ci', detect_project(str(self.root))['setup_commands'][0])
        self.assertEqual(detect_project(str(self.root))['verification_commands'], ['npm test -- --run'])

    def test_nested_python_package_is_detected_as_python_project(self):
        package = self.root / 'billing'
        package.mkdir()
        (package / '__init__.py').write_text('')
        tests = self.root / 'tests'
        tests.mkdir()
        (tests / 'test_billing.py').write_text('import unittest\n')
        detected = detect_project(str(self.root))
        self.assertEqual(detected['type'], 'python')
        self.assertEqual(detected['verification_commands'], ['python3 -m unittest discover -s tests -v'])

    def test_unseen_or_stale_existing_file_cannot_be_generated_over(self):
        for item in [
            {'path':'main.py','operation':'write_file','replacement':'oops'},
            {'path':'main.py','operation':'apply_patch','expected':'stale','replacement':'oops'}]:
            with self.subTest(item=item), self.assertRaises(ModelContractError):
                ModelGateway.validate_generation(turn([item]), {'files':{'main.py':'current'},'file_paths':['main.py']})

    def test_context_skips_external_symlink(self):
        outside = Path(self.temp.name)/'outside.py'
        outside.write_text('private=1')
        (self.root/'linked.py').symlink_to(outside)
        response = self.context.tools.call(ToolRequest('code','context', workspace_id=self.workspace.id, approval={'approved':True}))
        self.assertTrue(response.ok)
        self.assertNotIn('linked.py', response.data['files'])

    def test_malformed_and_oversized_patches_fail_instead_of_silent_truncation(self):
        for patches in [False, ['ignored'], [{'path':'x.py','content':'x'*(MAX_ITEM_CHARS+1)}],
                        [{'path':'C:\\escape.py','content':'oops'}], [{'path':'../x','content':'oops'}]]:
            with self.subTest(patches=str(patches)[:100]), self.assertRaises(ModelContractError):
                ModelGateway.validate_turn(turn(patches))

    def test_generation_retry_preserves_code_budget_and_requires_patches(self):
        gateway = ModelGateway()
        complete = json.dumps({'choices':[{'message':{'content':json.dumps(turn([{'path':'new.py','operation':'create','replacement':'answer=42\n'}]))}, 'finish_reason':'stop'}]})
        truncated = json.dumps({'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]})
        config = dict(self.remote, max_tokens=8192)
        with patch.object(gateway, '_request_completion', side_effect=[truncated, complete]) as request:
            result = gateway.plan('generate', {'require_patches':True,'files':{}}, settings_override=config)
        self.assertEqual(len(result['patches']), 1)
        self.assertEqual(request.call_args.kwargs['max_tokens'], 8192)
        self.assertIn('non-empty patches', request.call_args.args[3])
        self.assertNotIn('no patches', request.call_args.args[3])
