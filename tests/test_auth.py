import os
import tempfile
import unittest

from backend.auth import AuthService
from backend.h2_store import H2Store, find_h2_jar
from backend.store import JsonStore


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = AuthService(JsonStore(self.temp.name))

    def test_first_user_is_admin_and_password_is_hashed(self):
        admin = self.auth.register("admin", "password123")
        user = self.auth.register("alice", "password123")
        self.assertEqual(admin["role"], "ADMIN")
        self.assertEqual(user["role"], "USER")
        self.assertEqual(admin["balance"], 500)
        self.assertEqual(user["balance"], 500)
        token, logged = self.auth.login("admin", "password123")
        self.assertEqual(logged["id"], admin["id"])
        self.assertEqual(self.auth.user_from_token(token)["id"], admin["id"])
        with self.assertRaises(ValueError):
            self.auth.login("admin", "wrong-password")
        self.assertNotIn("password123", str(self.auth.store.read("users", [])))

    def test_admin_models_are_assigned_before_user_can_select_them(self):
        admin = self.auth.register("admin", "password123")
        user = self.auth.register("alice", "password123")
        model = self.auth.create_model({"name": "团队模型", "provider": "custom", "model": "team-v1", "api_key": "secret"})
        self.assertEqual(self.auth.list_models(user), [])
        self.auth.assign_model(user["id"], model["id"])
        available = self.auth.list_models(user)
        self.assertEqual([item["id"] for item in available], [model["id"]])
        self.assertNotIn("secret", str(available))
        self.assertEqual(self.auth.select_model(user, model["id"])["id"], model["id"])
        self.assertEqual(self.auth.list_models(admin)[0]["id"], "mdl_local")

    def test_selected_model_config_is_scoped_and_keeps_provider_secret_private(self):
        admin = self.auth.register("admin", "password123")
        user = self.auth.register("alice", "password123")
        model = self.auth.create_model({"name": "团队模型", "provider": "custom", "model": "team-v1", "base_url": "https://example.invalid/v1", "api_key": "secret"})
        self.auth.assign_model(user["id"], model["id"])
        config = self.auth.model_config(user, model["id"])
        self.assertEqual(config["model"], "team-v1")
        self.assertEqual(config["api_key"], "secret")
        with self.assertRaises(PermissionError):
            self.auth.model_config(user, "mdl_local")
        self.assertEqual(self.auth.model_config(admin, "mdl_local")["provider"], "local")

    def test_each_model_call_costs_one_and_admin_can_credit(self):
        admin = self.auth.register("admin", "password123")
        user = self.auth.register("alice", "password123")
        self.auth.assign_model(user["id"], "mdl_local")
        self.auth.consume(user["id"], "mdl_local", "request-1")
        self.assertEqual(self.auth.usage(user["id"])["total_cost"], 1)
        self.assertEqual(self.auth.user_from_token(self.auth.login("alice", "password123")[0])["balance"], 499)
        self.auth.credit(user["id"], 10)
        self.assertEqual(self.auth.user_from_token(self.auth.login("alice", "password123")[0])["balance"], 509)

    def test_daily_checkin_is_idempotent_and_adds_ten_points(self):
        user = self.auth.register("alice", "password123")
        before = self.auth.checkin_status(user["id"])
        self.assertFalse(before["claimed"])
        claimed = self.auth.checkin(user["id"])
        self.assertFalse(claimed["already_claimed"])
        self.assertEqual(claimed["balance"], 510)
        again = self.auth.checkin(user["id"])
        self.assertTrue(again["already_claimed"])
        self.assertEqual(again["balance"], 510)

    def test_default_prefers_configured_authorized_model_and_preserves_selection(self):
        admin = self.auth.register("admin", "password123")
        user = self.auth.register("alice", "password123")
        self.assertEqual(self.auth.selected_model(admin)["id"], "mdl_local")
        model = self.auth.create_model({"name": "Qwen", "provider": "custom", "model": "qwen",
                                       "base_url": "https://example.invalid/v1", "api_key": "secret"})
        self.assertEqual(self.auth.selected_model(admin)["id"], model["id"])
        self.assertIsNone(self.auth.selected_model(user))
        self.auth.assign_model(user["id"], "mdl_local")
        self.assertEqual(self.auth.selected_model(user)["id"], "mdl_local")
        self.auth.assign_model(user["id"], model["id"])
        self.assertEqual(self.auth.selected_model(user)["id"], model["id"])
        self.auth.select_model(user, "mdl_local")
        self.assertEqual(self.auth.selected_model(user)["id"], "mdl_local")
        self.auth.update_model(model["id"], {"enabled": False})
        self.assertEqual(self.auth.selected_model(admin)["id"], "mdl_local")

    def test_incomplete_model_does_not_displace_usable_default(self):
        admin = self.auth.register("admin", "password123")
        self.auth.create_model({"name": "Incomplete", "provider": "custom", "model": "qwen"})
        self.assertEqual(self.auth.selected_model(admin)["id"], "mdl_local")

    @unittest.skipUnless(find_h2_jar(), "H2 JDBC jar is not installed in this test environment")
    def test_h2_store_persists_accounts(self):
        path = os.path.join(self.temp.name, "h2")
        store = H2Store(path)
        self.addCleanup(store.close)
        auth = AuthService(store)
        auth.register("h2admin", "password123")
        self.assertEqual(auth.login("h2admin", "password123")[1]["role"], "ADMIN")
        self.assertTrue(os.path.exists(os.path.join(path, "accounts.mv.db")))
