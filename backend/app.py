import argparse
import io
import json
import mimetypes
import os
import re
import sys
import signal
import threading
import zipfile
from http import cookies
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote
from backend.previews import preview_asset

from backend.store import JsonStore
from backend.auth import AuthService
from backend.conversations import ConversationService, FREE_REPLY
from backend.generations import GenerationService
from backend.intent import IntentService
from backend.models import new_id
from backend.h2_store import H2Store
from backend.task_manager import TaskManager
from backend.workspaces import WorkspaceManager
from agent_client.executor import AgentExecutor
from agent_client.processes import ProcessManager
from backend.policy import ApprovalRequired
from backend.tool_protocol import ToolRequest
from backend.settings import SettingsService
from backend.model_gateway import ModelGateway
from backend.tool_service import ToolService
from backend.market import MarketService
from agent_client.remote import RemoteTools
import frontend


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.dirname(frontend.__file__)


class AppContext:
    def __init__(self, data_dir: str, agent_socket: str = ""):
        self.store = JsonStore(data_dir)
        self.auth_required = os.environ.get("CODESPIDER_AUTH_REQUIRED", "0") == "1"
        if self.auth_required:
            self.account_store = H2Store(os.path.join(data_dir, "h2"))
        else:
            self.account_store = JsonStore(os.path.join(data_dir, "accounts-dev"))
        self.auth = AuthService(self.account_store)
        self.conversations = ConversationService(self.account_store, self.store)
        self.workspaces = WorkspaceManager(self.store)
        if self.auth_required:
            admins = [item for item in self.account_store.read("users", []) if item.get("role") == "ADMIN"]
            if admins:
                self.workspaces.migrate_legacy_ownership(admins[0]["id"])
        self.market = MarketService(self.store, self.account_store)
        self.settings = SettingsService(self.store)
        self.processes = ProcessManager()
        self.tools = (RemoteTools(agent_socket, os.environ["CODESPIDER_IPC_TOKEN"])
                      if agent_socket else ToolService(self.store, self.workspaces, self.processes, self.market))
        self.tasks = TaskManager(self.store, self.workspaces, ModelGateway(self.settings), self.tools, self.market)

        self.generations = GenerationService(self)

    def generate_task(self, user, body, background=False, on_turn=None, progress=None, checkpoint=None, save_checkpoint=None):
        with self.conversations.serial(user["id"], body.get("workspace_id", "")):
            workspace = self.workspaces.get(body.get("workspace_id", ""), owner_id=user["id"])
            model = self.auth.selected_model(user)
            if self.auth_required and not model:
                raise ValueError("管理员尚未为当前用户分配模型")
            model_id = model["id"] if model else "mdl_local"
            model_settings = self.auth.model_config(user, model_id) if self.auth_required else None
            turn_id = ""
            def begin_turn():
                nonlocal turn_id
                if turn_id: return turn_id
                turn_id = self.conversations.begin(user["id"], body.get("workspace_id", ""), body.get("goal", ""))
                if on_turn: on_turn(turn_id)
                return turn_id
            try:
                history = self.conversations.context(user['id'], workspace.id)
                charge = (lambda: self.auth.consume(user['id'], model_id,
                    turn_id+':'+new_id('call') if background or body.get('intent_preview') else body.get('request_id',''))) if self.auth_required else None
                intent = None
                save = save_checkpoint
                if body.get('intent_preview') is True:
                    begin_turn()
                    checkpoint = IntentService(self.tasks.model).prepare(body['goal'],
                        {'workspace':{'name':workspace.name,'project_type':workspace.project_type,'description':workspace.description}, 'conversation':history},
                        model_settings or self.settings._raw(), checkpoint or {}, save_checkpoint or (lambda value: None), progress or (lambda value: None), charge)
                    intent = checkpoint['intent']
                    self.conversations.set_intent(turn_id, intent)
                    if save_checkpoint:
                        save = lambda value: save_checkpoint(dict(value, intent=intent, intent_signature=checkpoint['intent_signature']))
                task = self.tasks.create(body.get("workspace_id", ""), body.get("goal", ""), body.get("patches", []), model_id=model_id, model_settings=model_settings, context_approved=body.get("context_approved", False), on_model_call=charge, owner_id=user["id"], on_generation_start=begin_turn, conversation_context=history, plugin_id=body.get("plugin_id", ""), background_generation=background, progress=progress, checkpoint=checkpoint, save_checkpoint=save, intent=intent)
                self.conversations.finish(turn_id, reply=task.summary)
            except Exception as exc:
                if turn_id:
                    self.conversations.finish(turn_id, error=str(exc))
                raise
            return task

    def generate_chat(self, user, body, on_turn=None, progress=None, checkpoint=None, save_checkpoint=None):
        with self.conversations.serial(user['id'], ''):
            history = self.conversations.context(user['id'], '')
            turn_id = self.conversations.begin(user['id'], '', body['goal'])
            if on_turn: on_turn(turn_id)
            try:
                model = self.auth.selected_model(user)
                if self.auth_required and not model:
                    raise ValueError('管理员尚未为当前用户分配模型')
                model_id = model['id'] if model else 'mdl_local'
                settings = self.auth.model_config(user, model_id) if self.auth_required else self.settings._raw()
                charge = (lambda: self.auth.consume(user['id'], model_id, turn_id+':'+new_id('call'))) if self.auth_required else None
                intent = None
                if body.get('intent_preview') is True:
                    checkpoint = IntentService(self.tasks.model).prepare(body['goal'], {'workspace':None,'conversation':history},
                        settings, checkpoint or {}, save_checkpoint or (lambda value:None), progress or (lambda value:None), charge)
                    intent = checkpoint['intent']
                    self.conversations.set_intent(turn_id, intent)
                if progress: progress({'stage':'正在组织回答'})
                reply = self.tasks.model.chat(body['goal'], dict(history, intent=intent or {}), settings_override=settings, on_model_call=charge)
                timing = self.conversations.finish(turn_id, reply=reply)
                return {'reply':reply, 'timing':timing, 'intent':intent}
            except Exception as exc:
                self.conversations.finish(turn_id, error=str(exc))
                raise

    def close(self):
        self.generations.close()
        close = getattr(self.account_store, "close", None)
        if close:
            close()


class Handler(BaseHTTPRequestHandler):
    context: AppContext = None  # type: ignore

    def log_message(self, format: str, *args) -> None:
        message = re.sub(r'/preview/[a-f0-9]{48}', '/preview/[version]', format % args)
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), message))

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cookie_token(self) -> str:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:].strip()
        parsed = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return parsed.get("codespider_session").value if parsed.get("codespider_session") else ""

    def _user(self, required: bool = True):
        user = self.context.auth.user_from_token(self._cookie_token())
        if user:
            return user
        if not self.context.auth_required:
            return {"id": "local", "username": "local", "role": "ADMIN", "balance": 1_000_000, "selected_model_id": "mdl_local", "created_at": ""}
        if required:
            raise PermissionError("请先登录")
        return None

    def _require_admin(self):
        user = self._user()
        if user.get("role") != "ADMIN":
            raise PermissionError("只有管理员可以执行此操作")
        return user

    def _owned_task(self, task_id):
        task = self.context.tasks.get(task_id)
        user = self._user()
        if task.owner_id and task.owner_id != user["id"]:
            raise PermissionError("无权访问该会话任务")
        if not task.owner_id and user.get("role") != "ADMIN":
            raise PermissionError("无权访问历史未归属任务")
        self.context.workspaces.get(task.workspace_id, owner_id=user["id"])
        return task

    def _auth_json(self, status, payload, token=None, clear_cookie=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if token:
            self.send_header("Set-Cookie", "codespider_session=%s; HttpOnly; SameSite=Lax; Path=/; Max-Age=1209600" % token)
        elif clear_cookie:
            self.send_header("Set-Cookie", "codespider_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
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

    def _download_workspace(self, workspace_id: str, owner_id: str = "") -> None:
        workspace = self.context.workspaces.get(workspace_id, owner_id=owner_id)
        root = os.path.realpath(workspace.root)
        output = io.BytesIO()
        total = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for current, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [name for name in dirs if name not in {".git", "node_modules", "__pycache__", ".codespider"} and not os.path.islink(os.path.join(current, name))]
                for filename in sorted(files):
                    path = os.path.join(current, filename)
                    if os.path.islink(path) or not os.path.isfile(path):
                        continue
                    relative = os.path.relpath(path, root)
                    size = os.path.getsize(path)
                    total += size
                    if total > 100 * 1024 * 1024:
                        raise ValueError("工程压缩包不能超过 100 MB")
                    archive.write(path, relative)
        body = output.getvalue()
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", workspace.name).strip(".-") or "project"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="%s.zip"' % filename)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self):
        return urlparse(self.path)

    def _tool(self, tool, action, workspace_id="", arguments=None, approved=False, status=200):
        """Compatibility routes use the same Agent as the versioned API."""
        user = self._user()
        result = self.context.tools.call(ToolRequest(tool, action, arguments or {},
            workspace_id=workspace_id, owner_id=user["id"], approval={"approved": approved}))
        if result.ok:
            return self._json(status, result.data)
        error = result.error or {}
        status = 409 if error.get("approval_required") else 403 if error.get("code") == "FORBIDDEN" else 400
        return self._json(status, dict(error, error=error.get("message", "tool failed")))

    def do_GET(self) -> None:
        parsed = self._route()
        if parsed.path.startswith('/preview/'):
            return self._preview(parsed.path)
        if parsed.path == "/api/health":
            agent = self.context.tools.health() if isinstance(self.context.tools, RemoteTools) else {"ok": True, "mode": "embedded"}
            return self._json(200 if agent["ok"] else 503, {"ok": agent["ok"], "service": "codespider", "agent": agent, "instance": os.environ.get("CODESPIDER_INSTANCE", ""), "pid": os.getpid()})
        try:
            if parsed.path == "/api/auth/me":
                user = self._user(required=False)
                if not user:
                    return self._json(401, {"error": "请先登录"})
                return self._json(200, {"user": self.context.auth.public_user(user), "models": self.context.auth.list_models(user), "selected_model": self.context.auth.selected_model(user), "usage": self.context.auth.usage(user["id"])})
            if parsed.path == "/api/models":
                user = self._user()
                return self._json(200, {"items": self.context.auth.list_models(user), "selected": self.context.auth.selected_model(user)})
            if parsed.path == "/api/usage":
                user = self._user()
                return self._json(200, self.context.auth.usage(user["id"]))
            if parsed.path == "/api/auth/checkin":
                user = self._user()
                return self._json(200, self.context.auth.checkin_status(user["id"]))
            if parsed.path == "/api/admin/models":
                self._require_admin()
                return self._json(200, {"items": [self.context.auth.public_model(item, include_secret=True) for item in self.context.auth.store.read("models", [])]})
            if parsed.path == "/api/admin/users":
                self._require_admin()
                return self._json(200, {"items": self.context.auth.list_users()})
            if parsed.path.startswith("/api/"):
                self._user()
            if parsed.path == "/api/settings":
                return self._json(200, self.context.settings.public())
            if parsed.path == "/api/conversations":
                workspace_id = parse_qs(parsed.query).get("workspace_id", [""])[0]
                if workspace_id:
                    self.context.workspaces.get(workspace_id, owner_id=self._user()["id"])
                owner_id=self._user()["id"]
                jobs=[self.context.generations.get(j['id'],owner_id) for j in self.context.store.read('generations',[])
                      if j['owner_id']==owner_id and j['workspace_id']==workspace_id and j['status']!='completed']
                return self._json(200, {"items": self.context.conversations.history(owner_id, workspace_id), "generations": jobs})
            if parsed.path.startswith("/api/generations/"):
                return self._json(200, self.context.generations.get(parsed.path.split("/")[3], self._user()["id"]))
            if parsed.path == "/api/tools":
                return self._json(200, self.context.tools.catalog())
            if parsed.path == "/api/market":
                return self._json(200, self.context.market.catalog(self._user()["id"]))
            if parsed.path == "/api/workspaces":
                return self._json(200, {"items": [item.to_dict() for item in self.context.workspaces.list(self._user()["id"]) ]})
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/download"):
                return self._download_workspace(parsed.path.split("/")[3], self._user()["id"])
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
                self._owned_task(task_id)
                after = int(parse_qs(parsed.query).get("after", [0])[0])
                return self._json(200, {"items": [event.to_dict() for event in self.context.tasks.events(task_id, after)]})
            if parsed.path.startswith("/api/tasks/"):
                task = self._owned_task(parsed.path.split("/")[3])
                return self._json(200, self.context.conversations.task_payload(task.to_dict()))
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
        except PermissionError as exc:
            return self._json(401 if "登录" in str(exc) else 403, {"error": str(exc), "code": "AUTH_REQUIRED"})
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            return self._json(404 if isinstance(exc, KeyError) else 400, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = self._route()
        try:
            # Sandboxed generated pages have an opaque (null) origin. Never
            # accept their requests even when a browser attaches a session.
            origin = self.headers.get('Origin')
            if origin and (origin == 'null' or urlparse(origin).netloc != self.headers.get('Host')):
                raise PermissionError('不允许跨站修改请求')
            body = self._body()
            if parsed.path == "/api/auth/register":
                user = self.context.auth.register(body.get("username", ""), body.get("password", ""))
                if user["role"] == "ADMIN":
                    self.context.workspaces.migrate_legacy_ownership(user["id"])
                token, _ = self.context.auth.login(body.get("username", ""), body.get("password", ""))
                return self._auth_json(201, {"user": user}, token)
            if parsed.path == "/api/auth/login":
                token, user = self.context.auth.login(body.get("username", ""), body.get("password", ""))
                return self._auth_json(200, {"user": user, "models": self.context.auth.list_models(user), "selected_model": self.context.auth.selected_model(user), "usage": self.context.auth.usage(user["id"])}, token)
            if parsed.path == "/api/auth/logout":
                self.context.auth.logout(self._cookie_token())
                return self._auth_json(200, {"ok": True}, clear_cookie=True)
            user = self._user()
            if parsed.path == "/api/auth/checkin":
                return self._json(200, self.context.auth.checkin(user["id"]))
            if parsed.path == "/api/conversations/free":
                if body.get('async_generation') is True:
                    return self._json(202, self.context.generations.submit(user,
                        {'workspace_id':'','goal':body.get('text',''),'intent_preview':body.get('intent_preview') is True}, kind='chat'))
                with self.context.conversations.serial(user["id"], ""):
                    text = body.get("text", "")
                    history = self.context.conversations.context(user["id"], "")
                    turn_id = self.context.conversations.begin(user["id"], "", text)
                    try:
                        model = self.context.auth.selected_model(user)
                        if self.context.auth_required and not model:
                            raise ValueError("管理员尚未为当前用户分配模型")
                        model_id = model["id"] if model else "mdl_local"
                        settings = self.context.auth.model_config(user, model_id) if self.context.auth_required else None
                        if self.context.auth_required:
                            self.context.auth.consume(user["id"], model_id, turn_id)
                        reply = self.context.tasks.model.chat(str(text).strip(), history, settings_override=settings)
                        timing = self.context.conversations.finish(turn_id, reply=reply)
                    except Exception as exc:
                        self.context.conversations.finish(turn_id, error=str(exc))
                        raise
                    current_user = self.context.auth.user_from_token(self._cookie_token()) if self.context.auth_required else user
                    return self._json(201, {"id": turn_id, "reply": reply, "timing": timing, "balance": self.context.auth.public_user(current_user or user)["balance"]})
            if parsed.path == "/api/models/select":
                return self._json(200, {"selected": self.context.auth.select_model(user, str(body.get("model_id", "")))})
            if parsed.path == "/api/admin/models":
                self._require_admin()
                return self._json(201, self.context.auth.create_model(body))
            if parsed.path.startswith("/api/admin/models/") and parsed.path.endswith("/assign"):
                self._require_admin()
                self.context.auth.assign_model(str(body.get("user_id", "")), parsed.path.split("/")[4])
                return self._json(200, {"ok": True})
            if parsed.path.startswith("/api/admin/models/"):
                self._require_admin()
                return self._json(200, self.context.auth.update_model(parsed.path.split("/")[4], body))
            if parsed.path.startswith("/api/admin/users/") and parsed.path.endswith("/credit"):
                self._require_admin()
                return self._json(200, self.context.auth.credit(parsed.path.split("/")[4], int(body.get("amount", 0))))
            if parsed.path == "/api/tools/call":
                body["owner_id"] = user["id"]
                response = self.context.tools.call(body)
                status = 200 if response.ok else (409 if response.error and response.error.get("code") == "APPROVAL_REQUIRED" else 403 if response.error and response.error.get("code") == "FORBIDDEN" else 400)
                return self._json(status, response.to_dict())
            if parsed.path == "/api/settings":
                self._require_admin()
                return self._json(200, self.context.settings.update(body))
            if parsed.path == "/api/workspaces":
                workspace = self.context.workspaces.create(body.get("root", ""), body.get("name"), body.get("start_command", ""), body.get("description", ""), body.get("execution_mode", "safe"), body.get("command_allowlist", []), owner_id=user["id"], allow_external=user["role"] == "ADMIN")
                return self._json(201, workspace.to_dict())
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/recommendation"):
                workspace=self.context.workspaces.get(parsed.path.split("/")[3],owner_id=user["id"])
                return self._json(200,self.context.market.select(str(body.get("goal", ""))+"\n"+workspace.description,workspace.project_type,user["id"]))
            if parsed.path.startswith("/api/generations/") and parsed.path.endswith("/resume"):
                return self._json(202,self.context.generations.submit(user,{},parsed.path.split("/")[3]))
            if parsed.path == "/api/tasks":
                if body.get("async_generation") is True:
                    return self._json(202, self.context.generations.submit(user, body))
                task = self.context.generate_task(user, body)
                return self._json(201, self.context.conversations.task_payload(task.to_dict()))
            if parsed.path.endswith("/approve"):
                self._owned_task(parsed.path.split("/")[3])
                task = self.context.tasks.approve(parsed.path.split("/")[3])
                return self._json(200, self.context.conversations.task_payload(task.to_dict()))
            if parsed.path.endswith("/cancel"):
                self._owned_task(parsed.path.split("/")[3])
                task = self.context.tasks.cancel(parsed.path.split("/")[3])
                return self._json(200, self.context.conversations.task_payload(task.to_dict()))
            if parsed.path == "/api/memories":
                kind = body.get("type", "project")
                return self._tool("memory", kind, arguments=body, status=201)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/delete"):
                return self._tool("workspace", "delete", parsed.path.split("/")[3], body, body.get("confirmed") is True)
            if parsed.path.startswith("/api/workspaces/") and parsed.path.endswith("/settings"):
                workspace = self.context.workspaces.update(parsed.path.split("/")[3], body.get("name", ""), body.get("root", ""), body.get("start_command", ""), body.get("description", ""), body.get("execution_mode", "safe"), body.get("command_allowlist", []), owner_id=user["id"], allow_external=user["role"] == "ADMIN")
                return self._json(200, workspace.to_dict())
            if parsed.path == "/api/market/preferences":
                item_id = str(body.get("item_id", ""))
                return self._json(200, self.context.market.set_enabled(user["id"], item_id, body.get("enabled", True), body.get("installed")))
            if parsed.path == "/api/market/skills":
                return self._json(201, self.context.market.add_skill(user["id"], body))
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
        except PermissionError as exc:
            return self._json(401 if "登录" in str(exc) else 403, {"error": str(exc), "code": "AUTH_REQUIRED"})
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            return self._json(400, {"error": str(exc)})

    def _preview(self, path):
        try:
            parts = path.split('/', 3)
            token = parts[2]
            if len(parts) != 4:
                raise FileNotFoundError('无效预览路径')
            relative, body, preview_policy = preview_asset(self.context.store, self.context.workspaces, token, unquote(parts[3]), include_policy=True)
        except (OSError, ValueError, KeyError, PermissionError):
            return self._json(404, {'error': '预览不存在、已更新或工程已删除，请刷新预览'})
        # Restrict scripts to their own release, including when opened in a new
        # tab. No same-origin privilege, cookies, host API, frames or navigation.
        host = self.headers.get('Host', '')
        if not re.fullmatch(r'[A-Za-z0-9.\-\[\]:]+', host):
            return self._json(400, {'error': 'invalid host'})
        scheme = 'https' if self.headers.get('X-Forwarded-Proto') == 'https' else 'http'
        source = '%s://%s/preview/%s/' % (scheme, host, token)
        # allow-forms enables submit events and constraint validation for local
        # prototypes; form-action 'none' still blocks every network submission.
        csp = ("sandbox allow-scripts allow-forms; default-src 'none'; script-src 'unsafe-inline' %s; "
               "style-src 'unsafe-inline' %s; img-src data: blob: %s; font-src data: %s; "
               "media-src blob: %s; connect-src %s; base-uri 'none'; form-action 'none'; "
               "frame-ancestors 'self'") % ((source,) * 6)
        if preview_policy.get('runtime_eval'):
            # Vue 2's HTML template compiler needs Function(). The document
            # retains its opaque origin and release-only resource/API policy.
            csp = csp.replace("script-src 'unsafe-inline'", "script-src 'unsafe-inline' 'unsafe-eval'")
        self.send_response(200)
        content_type = mimetypes.guess_type(relative)[0] or 'application/octet-stream'
        if content_type.startswith('text/') or content_type in ('application/javascript', 'application/json'):
            content_type += '; charset=utf-8'
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Security-Policy', csp)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

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
        context.close()
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
