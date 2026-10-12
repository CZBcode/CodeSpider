import tempfile
import unittest

from backend.settings import SettingsService
from backend.store import JsonStore


class SettingsTests(unittest.TestCase):
    def test_model_settings_are_persisted_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as root:
            service = SettingsService(JsonStore(root))
            saved = service.update({"provider": "anthropic", "model": "claude-sonnet", "api_key": "sk-secret-1234", "temperature": 0.7})
            self.assertEqual(saved["provider"], "anthropic")
            self.assertEqual(saved["model"], "claude-sonnet")
            self.assertTrue(saved["api_key_set"])
            self.assertNotIn("sk-secret-1234", str(saved))
            cleared = service.update({"clear_api_key": True})
            self.assertFalse(cleared["api_key_set"])

