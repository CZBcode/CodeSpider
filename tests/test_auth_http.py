import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from backend.h2_store import find_h2_jar


@unittest.skipUnless(find_h2_jar(), "H2 JDBC jar is not installed in this test environment")
class AuthHttpTests(unittest.TestCase):
    def test_login_is_required_and_task_consumes_one_credit(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            project.mkdir()
            data = Path(temp) / "data"
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, CODESPIDER_AUTH_REQUIRED="1", CODESPIDER_H2_JAR=find_h2_jar())
            process = subprocess.Popen([sys.executable, "-m", "backend.app", "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(data)], cwd=Path(__file__).resolve().parent.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(lambda: process.poll() is None and process.terminate())
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    urllib.request.urlopen("http://127.0.0.1:%s/" % port, timeout=1)
                    break
                except OSError:
                    time.sleep(.1)
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            def request(path, body=None, expected=200):
                req = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
                try:
                    response = opener.open(req, timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    self.assertEqual(response.status, expected)
                    return json.load(response)
            request("/api/workspaces", expected=401)
            account = request("/api/auth/register", {"username": "admin", "password": "password123"}, 201)
            self.assertEqual(account["user"]["role"], "ADMIN")
            workspace = request("/api/workspaces", {"root": str(project)}, 201)
            task = request("/api/tasks", {"workspace_id": workspace["id"], "goal": "分析工程"}, 201)
            self.assertEqual(task["model_id"], "mdl_local")
            self.assertEqual(request("/api/auth/me")["usage"]["total_cost"], 1)
