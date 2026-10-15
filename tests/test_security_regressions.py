import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_client.executor import AgentExecutor
from agent_client.processes import ProcessManager
from backend.documents import generate_workspace_document
from backend.policy import ApprovalRequired, PolicyError, WorkspacePolicy
from backend.store import JsonStore
from backend.tool_protocol import ToolRequest
from backend.tool_service import ToolService
from backend.workspaces import WorkspaceManager
from code_intelligence.indexer import CodeIndexer


class SecurityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'project'
        self.root.mkdir()
        (self.root / 'main.py').write_text('def inside():\n    return "internal-marker"\n')
        self.policy = WorkspacePolicy(str(self.root))
        self.executor = AgentExecutor(self.policy)
        self.workspaces = WorkspaceManager(JsonStore(str(self.base / 'data')))
        self.workspace = self.workspaces.create(str(self.root))
        self.processes = ProcessManager()
        self.addCleanup(self.processes.close)
        self.tools = ToolService(self.workspaces.store, self.workspaces, self.processes)

    def test_non_boolean_approval_is_rejected_by_parser_and_dispatcher(self):
        for approved in ('false', 'true', 1, 0, None, [], {}):
            payload = {'tool': 'workspace', 'action': 'read_file', 'workspace_id': self.workspace.id,
                       'arguments': {'path': 'main.py'}, 'approval': {'approved': approved}}
            with self.subTest(approved=approved):
                with self.assertRaises(ValueError):
                    ToolRequest.from_dict(payload)
                self.assertFalse(self.tools.call(payload).ok)
                self.assertFalse(self.tools.call(ToolRequest('workspace', 'read_file', {'path': 'main.py'},
                    workspace_id=self.workspace.id, approval={'approved': approved})).ok)
        self.assertIn('inside', self.executor.read_file('main.py', approved=False))
        self.assertIn('inside', self.executor.read_file('main.py', approved=True))

    def test_destructive_command_variants_require_approval_even_when_allowlisted(self):
        # Classify only. No destructive command is executed in this test.
        commands = ['rm -rf build', 'rm -fr build', 'rm -r -f build', '/bin/rm --recursive --force build',
                    'rm build/file', 'env rm -fr build', 'sh -c "rm -fr build"',
                    'git clean -df', 'git reset --hard', 'git -C project clean --force -d']
        for command in commands:
            with self.subTest(command=command):
                policy = WorkspacePolicy(str(self.root), mode='divergent', command_allowlist=[command])
                with self.assertRaises(ApprovalRequired):
                    policy.validate_command(command)
                self.assertEqual(policy.validate_command(command, approved=True)[0], 'high')
        self.assertEqual(WorkspacePolicy(str(self.root), mode='divergent').validate_command('python3 -m compileall -q .')[0], 'low')

    def test_search_and_index_skip_outside_links_but_keep_internal_links(self):
        outside = self.base / 'outside.py'
        outside.write_text('def outside():\n    return "external-marker"\n')
        (self.root / 'linked.py').symlink_to(outside)
        (self.root / 'internal.py').symlink_to(self.root / 'main.py')
        with self.assertRaises(PolicyError):
            self.executor.read_file('linked.py', approved=True)
        self.assertEqual(self.executor.search('external-marker', approved=True), [])
        self.assertEqual(len(self.executor.search('internal-marker', approved=True)), 2)
        symbols = CodeIndexer(str(self.root), self.policy).build()
        self.assertNotIn('outside', [item['name'] for item in symbols])
        self.assertIn('internal.py', [item['path'] for item in symbols])

    def test_document_cannot_overwrite_outside_symlink_target(self):
        outside = self.base / 'outside.md'
        outside.write_text('keep')
        (self.root / 'CODESPIDER.md').symlink_to(outside)
        with self.assertRaises(PolicyError):
            generate_workspace_document(self.workspace)
        self.assertEqual(outside.read_text(), 'keep')

    def test_index_cache_read_and_write_reject_outside_links(self):
        cache = self.root / '.codespider' / 'symbols.json'
        cache.unlink()
        outside = self.base / 'outside.json'
        outside.write_text('[]')
        cache.symlink_to(outside)
        for operation in (lambda: CodeIndexer(str(self.root), self.policy).build(),
                          lambda: self.workspaces.symbols(self.workspace.id),
                          lambda: generate_workspace_document(self.workspace)):
            with self.assertRaises(PolicyError):
                operation()
        self.assertEqual(outside.read_text(), '[]')

    def test_index_cache_directory_cannot_redirect_writes(self):
        (self.root / '.codespider' / 'symbols.json').unlink()
        (self.root / '.codespider').rmdir()
        outside = self.base / 'external-cache'
        outside.mkdir()
        (self.root / '.codespider').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(PolicyError):
            CodeIndexer(str(self.root), self.policy).build()
        self.assertFalse((outside / 'symbols.json').exists())

    def test_symlink_swap_after_resolution_cannot_redirect_write(self):
        outside = self.base / 'outside.txt'
        outside.write_text('keep')
        target = self.root / 'race.txt'
        original_resolve = self.policy.resolve
        def resolve_and_swap(relative):
            result = original_resolve(relative)
            target.symlink_to(outside)
            return result
        with patch.object(self.policy, 'resolve', side_effect=resolve_and_swap):
            with self.assertRaises(OSError):
                self.executor.write_file('race.txt', 'overwrite', approved=True)
        self.assertEqual(outside.read_text(), 'keep')

    def test_normal_nested_writes_and_documents_still_work(self):
        self.executor.write_file('src/nested/new.py', 'value = 1\n', approved=True)
        self.executor.apply_patch('src/nested/new.py', 'value = 1\n', 'value = 2\n', approved=True)
        self.assertEqual(self.executor.read_file('src/nested/new.py', approved=True), 'value = 2\n')
        document = generate_workspace_document(self.workspace)
        self.assertEqual((self.root / document['path']).read_text(), document['content'])
