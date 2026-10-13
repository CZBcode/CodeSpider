import json
import tempfile
import unittest
from pathlib import Path

from backend.app import AppContext
from backend.policy import PolicyError
from backend.tool_protocol import ToolRequest


class P2WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.context = AppContext(str(self.base / 'data'))
        self.addCleanup(self.context.processes.close)
        self.addCleanup(self.context.tasks.executor.shutdown, wait=True)

    def call(self, workspace, tool, action, arguments=None):
        response = self.context.tools.call(ToolRequest(tool, action, arguments or {},
            workspace_id=workspace.id, approval={'approved': True}))
        self.assertTrue(response.ok, response.error)
        return response.data

    def test_failed_initial_index_does_not_register_and_retry_preserves_files(self):
        source = self.root / 'main.py'
        source.write_text('def keep_me(): pass\n')
        outside = self.base / 'outside'
        outside.mkdir()
        marker = outside / 'symbols.json'
        marker.write_text('do not overwrite')
        (self.root / '.codespider').symlink_to(outside, target_is_directory=True)
        for _ in range(2):
            with self.assertRaises(PolicyError):
                self.context.workspaces.create(str(self.root))
            self.assertEqual(self.context.workspaces.list(), [])
            self.assertEqual(source.read_text(), 'def keep_me(): pass\n')
            self.assertEqual(marker.read_text(), 'do not overwrite')
        (self.root / '.codespider').unlink()
        workspace = self.context.workspaces.create(str(self.root))
        self.assertEqual([item.id for item in self.context.workspaces.list()], [workspace.id])
        self.assertEqual(source.read_text(), 'def keep_me(): pass\n')

    def test_document_and_symbols_follow_external_renames_deletes_and_additions(self):
        (self.root / 'main.py').write_text('def old_name(): pass\n')
        (self.root / 'deleted.py').write_text('def removed(): pass\n')
        workspace = self.context.workspaces.create(str(self.root))
        first = self.call(workspace, 'document', 'generate')['content']
        self.assertIn('`old_name`', first)
        (self.root / 'main.py').write_text('def renamed(): pass\n')
        (self.root / 'deleted.py').unlink()
        (self.root / 'new.py').write_text('class Added: pass\n')
        # No explicit index call between edits and document generation.
        document = self.call(workspace, 'document', 'generate')['content']
        self.assertIn('`renamed`', document)
        self.assertIn('`Added`', document)
        self.assertNotIn('`old_name`', document)
        self.assertNotIn('`removed`', document)
        self.assertEqual((self.root / 'CODESPIDER.md').read_text(), document)
        (self.root / 'new.py').unlink()
        symbols = self.call(workspace, 'code', 'symbols')['items']
        self.assertEqual([item['name'] for item in symbols], ['renamed'])

    def test_document_refreshes_after_direct_file_tool_edit(self):
        (self.root / 'main.py').write_text('def old_name(): pass\n')
        workspace = self.context.workspaces.create(str(self.root))
        self.call(workspace, 'workspace', 'write_file', {'path': 'main.py', 'content': 'def from_tool(): pass\n'})
        document = self.call(workspace, 'document', 'generate')['content']
        self.assertIn('`from_tool`', document)
        self.assertNotIn('`old_name`', document)

    def test_task_refreshes_persisted_index_after_patches(self):
        (self.root / 'main.py').write_text('def old_name(): pass\n')
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'rename function', [
            {'path': 'main.py', 'expected': 'def old_name(): pass\n', 'replacement': 'def new_name(): pass\n'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'succeeded')
        cached = json.loads((self.root / '.codespider/symbols.json').read_text())
        self.assertEqual([item['name'] for item in cached], ['new_name'])
        document = self.call(workspace, 'document', 'generate')['content']
        self.assertIn('`new_name`', document)
        self.assertNotIn('`old_name`', document)

    def test_stale_later_patch_is_rejected_before_any_write(self):
        (self.root / 'main.py').write_text('def old_name(): pass\n')
        workspace = self.context.workspaces.create(str(self.root))
        task = self.context.tasks.create(workspace.id, 'partial change', [
            {'path': 'main.py', 'expected': 'def old_name(): pass\n', 'replacement': 'def new_name(): pass\n'},
            {'path': 'main.py', 'expected': 'no such text', 'replacement': 'unused'}])
        self.context.tasks.approve(task.id)
        self.context.tasks.executor.shutdown(wait=True)
        self.assertEqual(self.context.tasks.get(task.id).status, 'failed')
        symbols = self.call(workspace, 'code', 'symbols')['items']
        self.assertEqual([item['name'] for item in symbols], ['old_name'])
