import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from backend.model_gateway import ModelGateway
from backend.settings import SettingsService
from backend.store import JsonStore


class _ModelHandler(BaseHTTPRequestHandler):
    received = None

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        _ModelHandler.received = json.loads(self.rfile.read(size).decode())
        body = {"choices": [{"message": {"content": json.dumps({
            "schema": "agent.turn/v1", "summary": "ok",
            "thinking": [{"id": "t", "title": "理解", "summary": "ok", "status": "pending"}],
            "steps": [{"step": 1, "title": "检查", "action": "index", "detail": "ok"}],
            "tool_calls": [], "patches": []
        })}}]}
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args):
        pass


class ModelGatewayTests(unittest.TestCase):
    def test_openai_compatible_endpoint_is_parsed_and_validated(self):
        server = HTTPServer(("127.0.0.1", 0), _ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            settings = SettingsService(JsonStore(self.id()))
            settings.update({"provider": "custom", "model": "test-model", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "test-key"})
            turn = ModelGateway(settings).plan("test", {"project_type": "python"})
            self.assertEqual(turn["schema"], "agent.turn/v1")
            self.assertEqual(_ModelHandler.received["model"], "test-model")
            self.assertIn("test", _ModelHandler.received["messages"][1]["content"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
