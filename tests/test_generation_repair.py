import copy
import json
import unittest
from unittest.mock import patch

from backend.model_gateway import ModelGateway, ModelContractError, ModelRequestError
from backend.project_generator import ProjectGenerator
from code_intelligence.design_contract import DEFAULT_CONTRACT, review_proposal


CONFIG = {'model': 'fake', 'base_url': 'https://example.invalid/v1', 'api_key': 'test', 'max_tokens': 8192}


class GenerationRepairTests(unittest.TestCase):
    def setUp(self):
        self.model = ModelGateway()
        self.files = {'domain.py': 'def total():\n    return 5\n', 'tests/test_total.py': 'assert True\n'}
        self.design = {'modules': [{'path': 'domain.py', 'responsibility': '计算总数', 'depends_on': []}],
                       'interfaces': [{'path': 'domain.py', 'symbol': 'total', 'inputs': [], 'outputs': 'int', 'errors': []}], 'patterns': []}
        self.manifest = {'summary': '生成工程', 'files': [{'path': p, 'contract': '保持公开接口与功能'} for p in self.files],
                         'design': {'modules': [], 'interfaces': [], 'patterns': []}}
        self.context = {'files': {}, 'file_paths': [], 'design_contract': copy.deepcopy(DEFAULT_CONTRACT)}
        self.saved = {}; self.calls = []; self.charges = []
        self.repair = lambda data: {'design': self.design, 'files': []}

    def request(self, endpoint, settings, system, payload, **kwargs):
        kwargs['on_model_call']()
        data = json.loads(payload.split('\nCorrect the previous error:')[0]); self.calls.append(data)
        if 'blocking' in data:
            value = self.repair(data)
        elif 'current_file' in data:
            path = data['current_file']['path']
            if 'error' in data:
                value = {'path': path, 'replacement': self.files[path]}
            else:
                value = {'summary': '生成文件', 'patches': [{'path': path, 'operation': 'create', 'replacement': self.files[path]}]}
        else:
            value = self.manifest
        return json.dumps({'choices': [{'message': {'content': json.dumps(value)}}]})

    def save(self, value):
        snapshot = copy.deepcopy(value)
        self.saved.clear(); self.saved.update(snapshot)

    def run_generation(self, checkpoint=None):
        with patch.object(self.model, '_request_completion', side_effect=self.request), patch('backend.project_generator.time.sleep'):
            return ProjectGenerator(self.model).generate('生成项目', self.context, CONFIG,
                on_call=lambda: self.charges.append(1), checkpoint=checkpoint, save=self.save)

    def test_metadata_converges_without_regenerating_source(self):
        turn = self.run_generation()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(self.charges), 4)
        self.assertEqual({p['path']: p['replacement'] for p in turn['patches']}, self.files)
        self.assertEqual(turn['design'], self.design)
        self.assertTrue(self.saved['signature'])
        self.assertFalse(self.saved['validation_failed'])

    def test_no_progress_is_bounded_and_resume_keeps_draft(self):
        self.repair = lambda data: {'design': self.manifest['design'], 'files': []}
        with self.assertRaisesRegex(RuntimeError, '3 轮'):
            self.run_generation()
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(len(self.saved['patches']), 2)
        self.assertEqual(self.saved['repair']['status'], 'paused')
        self.repair = lambda data: {'design': self.design, 'files': []}
        self.run_generation(copy.deepcopy(self.saved))
        self.assertEqual(len(self.calls), 7)
        self.assertEqual(self.saved['repair']['round'], 4)

    def test_legacy_draft_recovers_without_manifest_or_file_requests(self):
        checkpoint = {'signature': '', 'validation_failed': True, 'manifest': self.manifest,
                      'patches': [{'path': p, 'operation': 'create', 'replacement': text} for p, text in self.files.items()]}
        self.run_generation(checkpoint)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('blocking', self.calls[0])

    def test_legacy_conflicting_files_are_rejected_without_overwriting_checkpoint(self):
        checkpoint = {'signature': '', 'validation_failed': True, 'manifest': self.manifest,
                      'patches': [{'path': p, 'operation': 'create', 'replacement': text} for p, text in self.files.items()]}
        self.context['files'] = {'domain.py': 'user edits'}
        self.context['file_paths'] = ['domain.py']
        with self.assertRaises(ModelContractError):
            self.run_generation(checkpoint)
        self.assertEqual(self.calls, []); self.assertEqual(self.saved, {})

    def test_metadata_repair_cannot_modify_source_or_escape_manifest(self):
        for paths in (['domain.py'], ['../escape.py'], ['design-contract.json']):
            with self.subTest(paths=paths):
                self.repair = lambda data: {'design': self.design, 'files': paths}
                with self.assertRaises(RuntimeError):
                    self.run_generation()
                self.assertEqual({p['path']: p['replacement'] for p in self.saved['patches']}, self.files)

    def test_pending_source_repair_resumes_and_keeps_original_preconditions(self):
        self.context['design_contract']['mode'] = 'enforce'
        self.context['files'] = {'domain.py': 'original = True\n'}
        self.context['file_paths'] = ['domain.py']
        checkpoint = {'signature': '', 'validation_failed': True, 'manifest': self.manifest,
                      'patches': [{'path': 'domain.py', 'operation': 'apply_patch', 'expected': 'original = True\n', 'replacement': 'def broken(:\n'},
                                  {'path': 'tests/test_total.py', 'operation': 'create', 'replacement': self.files['tests/test_total.py']}]}
        self.repair = lambda data: {'design': self.design, 'files': ['domain.py']}
        original = self.request
        def interrupted(*args, **kwargs):
            if '"current_file"' in args[3]:
                raise ModelRequestError('timeout', True)
            return original(*args, **kwargs)
        with patch.object(self, 'request', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.run_generation(checkpoint)
        self.assertEqual(self.saved['repair']['pending'], ['domain.py'])
        self.assertEqual(len(self.saved['patches']), 2)
        turn = self.run_generation(copy.deepcopy(self.saved))
        self.assertEqual(turn['patches'][0]['replacement'], self.files['domain.py'])
        self.assertEqual(turn['patches'][0]['expected'], 'original = True\n')
        self.assertEqual(sum('blocking' in c for c in self.calls), 1)
        self.assertEqual(turn['patches'][1], checkpoint['patches'][1])

    def test_typescript_tests_excluded_but_config_still_documented(self):
        files = [{'path': 'src/__tests__/card.spec.ts', 'operation': 'create', 'replacement': 'export function testCard() {}'},
                 {'path': 'vite.config.ts', 'operation': 'create', 'replacement': 'export default {}'}]
        with self.assertRaisesRegex(ValueError, 'vite.config.ts') as error:
            review_proposal(self.context, files, self.manifest['design'])
        self.assertNotIn('card.spec.ts', str(error.exception))

    def test_completed_file_repair_is_not_repeated_after_interruption(self):
        self.context['design_contract']['mode'] = 'enforce'
        self.files['service.py'] = 'def service():\n    return 1\n'
        self.manifest['files'].append({'path': 'service.py', 'contract': 'service returns 1'})
        self.design['modules'].append({'path': 'service.py', 'responsibility': '应用服务', 'depends_on': []})
        checkpoint = {'signature': '', 'validation_failed': True, 'manifest': self.manifest,
                      'patches': [{'path': p, 'operation': 'create', 'replacement': 'def broken(:\n' if p != 'tests/test_total.py' else text}
                                  for p, text in self.files.items()]}
        self.repair = lambda data: {'design': self.design, 'files': ['domain.py', 'service.py']}
        original = self.request
        def interrupted(*args, **kwargs):
            data = json.loads(args[3].split('\nCorrect the previous error:')[0])
            if data.get('current_file', {}).get('path') == 'service.py':
                raise ModelRequestError('timeout', True)
            return original(*args, **kwargs)
        with patch.object(self, 'request', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.run_generation(checkpoint)
        self.assertEqual(self.saved['repair']['pending'], ['service.py'])
        self.run_generation(copy.deepcopy(self.saved))
        self.assertEqual(sum(c.get('current_file', {}).get('path') == 'domain.py' for c in self.calls), 1)
        self.assertEqual(sum('blocking' in c for c in self.calls), 1)

    def test_stale_existing_source_precondition_preserves_saved_draft(self):
        checkpoint = {'signature': '', 'validation_failed': True, 'manifest': self.manifest,
                      'patches': [{'path': 'domain.py', 'operation': 'apply_patch', 'expected': 'before', 'replacement': self.files['domain.py']}]}
        self.context['files'] = {'domain.py': 'after manual edit'}
        with self.assertRaisesRegex(ModelContractError, 'expected'):
            self.run_generation(checkpoint)
        self.assertEqual(self.saved, {})

    def test_typescript_declarations_are_real_design_evidence(self):
        source = '''export interface Course { id: string; }
export interface Page<T> extends Collection<T> { items: T[]; }
export type CourseId = string;
export type Result<T> = { value: T };
export enum Status { Active, Closed }
// interface Ghost { }
const text = "type Fake = string";
'''
        names = ['Course', 'Page', 'CourseId', 'Result', 'Status']
        design = {'modules': [{'path': 'types.ts', 'responsibility': '公共数据类型', 'depends_on': []}],
                  'interfaces': [{'path': 'types.ts', 'symbol': name, 'inputs': [], 'outputs': 'type', 'errors': []} for name in names], 'patterns': []}
        proposal = [{'path': 'types.ts', 'operation': 'create', 'replacement': source}]
        report = review_proposal(self.context, proposal, design)
        indexed = {s['name'] for s in report['modules'][0]['symbols']}
        self.assertTrue(set(names) <= indexed)
        self.assertTrue({'Ghost', 'Fake'}.isdisjoint(indexed))

    def test_typed_interface_and_class_methods_have_exact_owners(self):
        from code_intelligence.structure import review_structure
        source = '''export interface ApiClient {
  get<T>(url: string): Promise<T>;
  delete(url: string): Promise<void>;
}
export class FetchApiClient implements ApiClient {
  async get<T>(url: string): Promise<T> {
    function local() { return 1; }
    return fetch(url);
  }
  async delete(url: string): Promise<void> { await fetch(url); }
}
export class CourseService {
  async enrollCourse(
    studentId: string,
    courseId: string
  ): Promise<string> { return courseId; }
}
'''
        report = review_structure({'api.ts': source}, DEFAULT_CONTRACT)
        names = {s.get('qualified_name') for s in report['modules'][0]['symbols']}
        self.assertTrue({'ApiClient.get', 'ApiClient.delete', 'FetchApiClient.get', 'FetchApiClient.delete', 'CourseService.enrollCourse'} <= names)
        self.assertNotIn('FetchApiClient.local', names)
        self.assertNotIn('ApiClient.enrollCourse', names)

    def test_metadata_diagnostic_identifies_exact_invalid_field(self):
        self.design['interfaces'][0]['outputs'] = ''
        with self.assertRaisesRegex(ValueError, 'interface domain.py total outputs'):
            review_proposal(self.context, [{'path': p, 'operation': 'create', 'replacement': text} for p, text in self.files.items()], self.design)

    def test_legacy_public_status_offers_repair_without_exposing_source(self):
        from types import SimpleNamespace
        from backend.generations import GenerationService
        job = {'id': 'job', 'owner_id': 'alice', 'workspace_id': 'project', 'status': 'failed',
               'request': {'goal': '生成项目'}, 'error': '点击继续生成会重新规划',
               'checkpoint': {'signature': '', 'validation_failed': True, 'patches': [{'replacement': 'private source'}]}}
        service = GenerationService.__new__(GenerationService)
        service.store = SimpleNamespace(read=lambda *args: [job])
        service.context = SimpleNamespace(workspaces=SimpleNamespace(get=lambda *args, **kwargs: None))
        result = service.get('job', 'alice')
        self.assertIn('继续修复', result['error'])
        self.assertNotIn('重新规划', result['error'])
        self.assertNotIn('private source', json.dumps(result))
        self.assertEqual(result['draft']['files'], 1)
        with self.assertRaises(PermissionError):
            service.get('job', 'bob')


if __name__ == '__main__':
    unittest.main()
