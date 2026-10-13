import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from backend.model_gateway import ModelGateway
from backend.settings import SettingsService
from backend.store import JsonStore


class _ModelHandler(BaseHTTPRequestHandler):
    received = None
    requests = []
    responses = []

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        _ModelHandler.received = json.loads(self.rfile.read(size).decode())
        _ModelHandler.requests.append(_ModelHandler.received)
        content = _ModelHandler.responses.pop(0) if _ModelHandler.responses else json.dumps({
            "schema": "agent.turn/v1", "summary": "ok",
            "thinking": [{"id": "t", "title": "理解", "summary": "ok", "status": "pending"}],
            "steps": [{"step": 1, "title": "检查", "action": "index", "detail": "ok"}],
            "tool_calls": [], "patches": []
        })
        body = {"choices": [{"message": {"content": content}}]}
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        pass


class ModelGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_openai_compatible_endpoint_is_parsed_and_validated(self):
        _ModelHandler.responses = []
        _ModelHandler.requests = []
        server = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = SettingsService(JsonStore(self.temp.name))
            settings.update({"provider": "custom", "model": "test-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "test-key"})
            turn = ModelGateway(settings).plan("test", {"project_type": "python"})
            self.assertEqual(turn["schema"], "agent.turn/v1")
            self.assertEqual(_ModelHandler.received["model"], "test-model")
            self.assertIn("test", _ModelHandler.received["messages"][1]["content"])
        finally:
            server.shutdown()
            server.server_close()

    def test_settings_override_routes_to_selected_model(self):
        _ModelHandler.responses = []
        _ModelHandler.requests = []
        server = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = SettingsService(JsonStore(self.temp.name))
            settings.update({"provider": "custom", "model": "global-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "global-key"})
            override = {"provider": "custom", "model": "selected-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "selected-key"}
            turn = ModelGateway(settings).plan("test", {"project_type": "python"}, settings_override=override)
            self.assertEqual(turn["schema"], "agent.turn/v1")
            self.assertEqual(_ModelHandler.received["model"], "selected-model")
        finally:
            server.shutdown()
            server.server_close()

    def test_normalizes_provider_wrappers_and_patch_aliases(self):
        wrapped = {"agent.turn": {"summary": "wrapped", "thinking": ["read"], "steps": ["inspect"], "tool_calls": [], "patches": [{"file": "main.py", "old": "x = 1\n", "new": "x = 2\n"}]}}
        turn = ModelGateway.validate_turn(wrapped)
        self.assertEqual(turn["schema"], "agent.turn/v1")
        self.assertEqual(turn["thinking"][0]["summary"], "read")
        self.assertEqual(turn["patches"][0]["operation"], "apply_patch")
        self.assertEqual(turn["patches"][0]["path"], "main.py")

    def test_missing_thoughts_and_steps_do_not_block_valid_code(self):
        turn = ModelGateway.validate_turn({"summary": "Ready for approval", "patches": [
            {"path": "main.py", "operation": "create", "replacement": "answer = 42\n"}]})
        ModelGateway.validate_generation(turn, {"files": {}})
        self.assertEqual(turn["thinking"], [])
        self.assertEqual(turn["steps"], [])
        with self.assertRaises(ValueError):
            ModelGateway.validate_generation(ModelGateway.validate_turn({"summary": "No changes"}), {"files": {}})

    def test_incomplete_remote_model_never_falls_back_to_demo(self):
        from backend.model_gateway import ModelRequestError
        for missing in ("base_url", "api_key"):
            settings = {"provider": "custom", "model": "qwen", "base_url": "https://example.invalid", "api_key": "secret"}
            settings.pop(missing)
            with self.assertRaises(ModelRequestError):
                ModelGateway().plan("Generate code", {}, settings_override=settings)

    def test_normalizes_string_response_wrapper_and_schema_alias(self):
        wrapped = {"response": json.dumps({
            "type": "agent.turn/v1", "summary": "wrapped", "thinking": ["read"],
            "steps": ["inspect"], "tool_calls": [], "patches": []
        })}
        turn = ModelGateway.validate_turn(wrapped)
        self.assertEqual(turn["schema"], "agent.turn/v1")
        self.assertEqual(turn["steps"][0]["detail"], "inspect")

    def test_retries_with_contract_repair_after_malformed_response(self):
        _ModelHandler.requests = []
        _ModelHandler.responses = ["{\"agent\": {\"turn\": \"v1\"}, \"summary\": \"\"}", json.dumps({
            "schema": "agent.turn/v1", "summary": "repaired",
            "thinking": [{"id": "t", "title": "理解", "summary": "ok", "status": "pending"}],
            "steps": [{"step": 1, "title": "检查", "action": "index", "detail": "ok"}],
            "tool_calls": [], "patches": []
        })]
        server = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = SettingsService(JsonStore(self.temp.name))
            settings.update({"provider": "custom", "model": "test-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "test-key"})
            turn = ModelGateway(settings).plan("test", {"project_type": "python"})
            self.assertEqual(turn["summary"], "repaired")
            self.assertEqual(len(_ModelHandler.responses), 0)
            self.assertEqual(len(_ModelHandler.requests), 2)
            self.assertEqual(_ModelHandler.requests[1]["max_tokens"], 1200)
            self.assertIn("smallest valid response", _ModelHandler.requests[1]["messages"][0]["content"])
        finally:
            server.shutdown()
            server.server_close()

    def test_retries_after_truncated_json_response(self):
        _ModelHandler.requests = []
        _ModelHandler.responses = [
            '{"schema":"agent.turn/v1","summary":"truncated","thinking":[{"id":"t",',
            json.dumps({
                "schema": "agent.turn/v1", "summary": "recovered",
                "thinking": [{"id": "t", "title": "理解", "summary": "ok", "status": "pending"}],
                "steps": [
                    {"step": 1, "title": "检查", "action": "index", "detail": "ok"},
                    {"step": 2, "title": "执行", "action": "agent", "detail": "ok"},
                    {"step": 3, "title": "验证", "action": "verify", "detail": "ok"},
                ],
                "tool_calls": [], "patches": []
            })
        ]
        server = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = SettingsService(JsonStore(self.temp.name))
            settings.update({"provider": "custom", "model": "test-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "test-key"})
            turn = ModelGateway(settings).plan("test", {"project_type": "python"})
            self.assertEqual(turn["summary"], "recovered")
            self.assertEqual(len(_ModelHandler.requests), 2)
            self.assertEqual(_ModelHandler.requests[1]["max_tokens"], 1200)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
