import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.store import JsonStore
from backend.workspaces import WorkspaceManager


class WorkspaceCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        # Redirect only home expansion; never create test projects in the user's home.
        expanduser = os.path.expanduser
        mock = patch('backend.workspaces.os.path.expanduser', side_effect=lambda path:
            str(self.home / path[2:]) if path.startswith('~/') else expanduser(path))
        mock.start()
        self.addCleanup(mock.stop)
        self.manager = WorkspaceManager(JsonStore(str(self.home / 'custom-data')))

    def test_name_only_creates_default_project_and_persists_absolute_path(self):
        workspace = self.manager.create(name=' 示例工程 ')
        expected = self.home / '.codespider' / 'project' / '示例工程'
        self.assertTrue(expected.is_dir())
        self.assertEqual(workspace.root, str(expected))
        self.assertEqual(self.manager.get(workspace.id).root, str(expected))
        marker = expected / 'existing.txt'
        marker.write_text('keep')
        self.manager.create('', '示例工程')
        self.assertEqual(marker.read_text(), 'keep')

    def test_explicit_existing_path_is_preserved(self):
        existing = self.home / 'existing'
        existing.mkdir()
        workspace = self.manager.create(str(existing))
        self.assertEqual(workspace.root, str(existing))
        self.assertEqual(workspace.name, 'existing')
        self.assertFalse((self.home / '.codespider' / 'project').exists())

    def test_invalid_names_cannot_create_outside_default_directory(self):
        for name in ('', ' ', '.', '..', '../escape', '/tmp/escape', 'a/b', 'a\\b', 'a\0b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.manager.create(name=name)
        self.assertEqual(self.manager.list(), [])

    def test_existing_symlink_cannot_redirect_default_project_outside_base(self):
        base = self.home / '.codespider' / 'project'
        base.mkdir(parents=True)
        (base / 'escape').symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.manager.create(name='escape')
