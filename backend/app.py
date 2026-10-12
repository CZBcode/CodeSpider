import argparse
import json
import mimetypes
import os
import sys
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from backend.store import JsonStore
from backend.task_manager import TaskManager
from backend.workspaces import WorkspaceManager
from agent_client.executor import AgentExecutor
from agent_client.processes import ProcessManager
from backend.policy import ApprovalRequired
from backend.tool_protocol import ToolRequest
from backend.settings import SettingsService
from backend.model_gateway import ModelGateway
from backend.tool_service import ToolService
from agent_client.remote import RemoteTools
import frontend


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.dirname(frontend.__file__)


class AppContext:
    def __init__(self, data_dir: str, agent_socket: str = ""):
        self.store = JsonStore(data_dir)
        self.workspaces = WorkspaceManager(self.store)
        self.settings = SettingsService(self.store)
        self.processes = ProcessManager()
        self.tools = (RemoteTools(agent_socket, os.environ["CODESPIDER_IPC_TOKEN"])
                      if agent_socket else ToolService(self.store, self.workspaces, self.processes))
        self.tasks = TaskManager(self.store, self.workspaces, ModelGateway(self.settings), self.tools)


class Handler(BaseHTTPRequestHandler):
    context: AppContext = None  # type: ignore

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 2 * 1024 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(size) if size else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _route(self):
        return urlparse(self.path)

    def _tool(self, tool, action, workspace_id="", arguments=None, approved=False, status=200):
        """Compatibility routes use the same Agent as the versioned API."""
        result = self.context.tools.call(ToolRequest(tool, action, arguments or {},
            workspace_id=workspace_id, approval={"approved": approved}))
        if result.ok:
            return self._json(status, result.data)
        error = result.error or {}
        status = 409 if error.get("approval_required") else 400
        return self._json(status, dict(error, error=error.get("message", "tool failed")))

    def do_GET(self) -> None:
        parsed = self._route()
        if parsed.path == "/api/health":
            agent = self.context.tools.health() if isinstance(self.context.tools, RemoteTools) else {"ok": True, "mode": "embedded"}
            return self._json(200 if agent["ok"] else 503, {"ok": agent["ok"], "service": "codespider", "agent": agent, "instance": os.environ.get("CODESPIDER_INSTANCE", ""), "pid": os.getpid()})
        try:
            if parsed.path == "/api/settings":
                return self._json(200, self.context.settings.public())
            if parsed.path == "/api/tools":
                return self._json(200, self.context.tools.catalog())
            if parsed.path == "/api/workspaces":
                return self._json(200, {"items": [item.to_dict() for item in self.context.workspaces.list()]})
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/tree"):
                workspace_id = parsed.path.split("/")[3]
                return self._tool("workspace", "list_tree", workspace_id)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/symbols"):
                workspace_id = parsed.path.split("/")[3]
                approved = parse_qs(parsed.query).get("approved", ["0"])[0] == "1"
                return self._tool("code", "symbols", workspace_id, approved=approved)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/file"):
                workspace_id = parsed.path.split("/")[3]
                relative_path = parse_qs(parsed.query).get("path", [""])[0]
                approved = parse_qs(parsed.query).get("approved", ["0"])[0] == "1"
                return self._tool("workspace", "read_file", workspace_id, {"path": relative_path}, approved)
            if parsed.path.startswith("/api/tasks/") and parsed.path.endswith("/events"):
                parts = parsed.path.split("/")
                task_id = parts[3]
                after = int(parse_qs(parsed.query).get("after", [0])[0])
                return self._json(200, {"items": [event.to_dict() for event in self.context.tasks.events(task_id, after)]})
            if parsed.path.startswith("/api/tasks/"):
                task = self.context.tasks.get(parsed.path.split("/")[3])
                return self._json(200, task.to_dict())
            if parsed.path == "/api/memories/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                scope_id = parse_qs(parsed.query).get("scope_id", ["global"])[0]
                return self._tool("memory", "search", arguments={"scope_id": scope_id, "query": query})
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/processes"):
                workspace_id = parsed.path.split("/")[3]
                return self._tool("process", "list", workspace_id)
            return self._static(parsed.path)
        except ApprovalRequired as exc:
            return self._json(409, {"error": exc.reason, "approval_required": True, "operation": exc.operation, "risk": exc.risk})
        except (KeyError, ValueError, OSError) as exc:
            return self._json(404 if isinstance(exc, KeyError) else 400, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = self._route()
        try:
            body = self._body()
            if parsed.path == "/api/tools/call":
                response = self.context.tools.call(body)
                status = 200 if response.ok else (409 if response.error and response.error.get("code") == "APPROVAL_REQUIRED" else 400)
                return self._json(status, response.to_dict())
            if parsed.path == "/api/settings":
                return self._json(200, self.context.settings.update(body))
            if parsed.path == "/api/workspaces":
                workspace = self.context.workspaces.create(body.get("root", ""), body.get("name"), body.get("start_command", ""), body.get("description", ""), body.get("execution_mode", "safe"), body.get("command_allowlist", []))
                return self._json(201, workspace.to_dict())
            if parsed.path == "/api/tasks":
                task = self.context.tasks.create(body.get("workspace_id", ""), body.get("goal", ""), body.get("patches", []))
                return self._json(201, task.to_dict())
            if parsed.path.endswith("/approve"):
                task = self.context.tasks.approve(parsed.path.split("/")[3])
                return self._json(200, task.to_dict())
            if parsed.path.endswith("/cancel"):
                task = self.context.tasks.cancel(parsed.path.split("/")[3])
                return self._json(200, task.to_dict())
            if parsed.path == "/api/memories":
                kind = body.get("type", "project")
                return self._tool("memory", kind, arguments=body, status=201)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/settings"):
                workspace = self.context.workspaces.update(parsed.path.split("/")[3], body.get("name", ""), body.get("root", ""), body.get("start_command", ""), body.get("description", ""), body.get("execution_mode", "safe"), body.get("command_allowlist", []))
                return self._json(200, workspace.to_dict())
            if parsed.path == "/api/documents/generate":
                return self._tool("document", "generate", body.get("workspace_id", ""), body, body.get("approved", False), 201)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/run"):
                return self._tool("process", "run", parsed.path.split("/")[3], body, body.get("approved", False))
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/processes"):
                return self._tool("process", "start", parsed.path.split("/")[3], body, body.get("approved", False), 201)
            if parsed.path.startswith("/api/processes/") and parsed.path.endswith("/stop"):
                return self._tool("process", "stop", body.get("workspace_id", ""), {"pid": int(parsed.path.split("/")[3])})
            return self._json(404, {"error": "route not found"})
        except ApprovalRequired as exc:
            return self._json(409, {"error": exc.reason, "approval_required": True, "operation": exc.operation, "risk": exc.risk})
        except (KeyError, ValueError, OSError) as exc:
            return self._json(400, {"error": str(exc)})

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = os.path.realpath(os.path.join(FRONTEND_DIR, relative))
        if not candidate.startswith(os.path.realpath(FRONTEND_DIR) + os.sep) and candidate != os.path.realpath(FRONTEND_DIR):
            return self._json(403, {"error": "invalid asset path"})
        if not os.path.isfile(candidate):
            return self._json(404, {"error": "asset not found"})
        with open(candidate, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str, port: int, workspace: str = "", data_dir: str = "", agent_socket: str = "") -> None:
    data_dir = data_dir or os.path.join(BASE_DIR, ".codespider")
    context = AppContext(data_dir, agent_socket)
    if workspace:
        context.workspaces.create(workspace)
    Handler.context = context
    server = ThreadingHTTPServer((host, port), Handler)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)
    print("CodeSpider listening on http://%s:%s" % (host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AgentExecutor.close_commands()
        context.tasks.executor.shutdown(wait=True)
        context.processes.close()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CodeSpider local agent workspace")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--workspace", default="")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--agent-socket", default="")
    args = parser.parse_args()
    run(args.host, args.port, args.workspace, args.data_dir, args.agent_socket)
