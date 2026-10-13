"""Local accounts, model access, sessions, balances, and usage accounting."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.models import new_id, now_iso


SESSION_DAYS = 14


def _password_hash(password: str, salt: bytes = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240000)
    return "pbkdf2_sha256$240000$%s$%s" % (salt.hex(), digest.hex())


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def _valid_username(value: str) -> bool:
    return 3 <= len(value) <= 48 and all(char.isalnum() or char in "._-" for char in value)


class AuthService:
    def __init__(self, store: Any):
        self.store = store
        self._bootstrap()

    def _bootstrap(self):
        self.store.update("users", [], lambda users: users)
        self.store.update("sessions", [], lambda sessions: sessions)
        self.store.update("models", [], lambda models: models)
        self.store.update("user_models", [], lambda items: items)
        self.store.update("usage", [], lambda items: items)
        if not self.store.read("models", []):
            self.store.append("models", {"id": "mdl_local", "name": "本地确定性模型", "provider": "local", "model": "deterministic-mvp", "base_url": "", "api_key": "", "enabled": True, "created_at": now_iso()})

    def register(self, username: str, password: str) -> Dict[str, Any]:
        username = str(username or "").strip()
        password = str(password or "")
        if not _valid_username(username):
            raise ValueError("用户名需为 3-48 位字母、数字、下划线、点或短横线")
        if len(password) < 8 or len(password) > 256:
            raise ValueError("密码长度需为 8-256 位")
        user = {"id": new_id("usr"), "username": username, "password_hash": _password_hash(password),
                "role": "USER", "balance": 10,
                "created_at": now_iso(), "active": True}
        def add(users):
            if any(item["username"].lower() == username.lower() for item in users):
                raise ValueError("用户名已存在")
            stored = dict(user, role="ADMIN" if not users else "USER")
            user.update(stored)
            return users + [stored]
        self.store.update("users", [], add)
        return self.public_user(user)

    def login(self, username: str, password: str) -> (str, Dict[str, Any]):
        user = next((item for item in self.store.read("users", []) if item["username"].lower() == str(username or "").strip().lower()), None)
        if not user or not user.get("active") or not _password_matches(str(password or ""), user["password_hash"]):
            raise ValueError("用户名或密码错误")
        raw = secrets.token_urlsafe(40)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
        self.store.append("sessions", {"token_hash": token_hash, "user_id": user["id"], "expires_at": expires})
        return raw, self.public_user(user)

    def logout(self, token: str) -> None:
        digest = hashlib.sha256(str(token or "").encode()).hexdigest()
        self.store.update("sessions", [], lambda items: [item for item in items if item["token_hash"] != digest])

    def user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        session = next((item for item in self.store.read("sessions", []) if hmac.compare_digest(item["token_hash"], digest)), None)
        if not session:
            return None
        try:
            if datetime.fromisoformat(session["expires_at"]) <= now:
                self.logout(token)
                return None
        except ValueError:
            return None
        return next((item for item in self.store.read("users", []) if item["id"] == session["user_id"] and item.get("active")), None)

    @staticmethod
    def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": user["id"], "username": user["username"], "role": user["role"], "balance": int(user.get("balance", 0)), "selected_model_id": user.get("selected_model_id", ""), "created_at": user["created_at"]}

    def list_users(self) -> List[Dict[str, Any]]:
        return [self.public_user(item) for item in self.store.read("users", [])]

    def create_model(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        provider = str(payload.get("provider", "custom")).strip().lower()
        model = str(payload.get("model", "")).strip()
        if not name or not model:
            raise ValueError("模型名称和模型标识不能为空")
        item = {"id": new_id("mdl"), "name": name, "provider": provider, "model": model,
                "base_url": str(payload.get("base_url", "")).strip(), "api_key": str(payload.get("api_key", "")),
                "enabled": bool(payload.get("enabled", True)), "created_at": now_iso()}
        self.store.append("models", item)
        return self.public_model(item, include_secret=True)

    def update_model(self, model_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        models = self.store.read("models", [])
        current = next((item for item in models if item["id"] == model_id), None)
        if not current:
            raise KeyError("model not found")
        updated = dict(current)
        for field in ("name", "provider", "model", "base_url"):
            if field in payload and str(payload[field]).strip():
                updated[field] = str(payload[field]).strip()
        if "api_key" in payload and str(payload.get("api_key", "")).strip():
            updated["api_key"] = str(payload["api_key"]).strip()
        if "enabled" in payload:
            updated["enabled"] = bool(payload["enabled"])
        self.store.update("models", [], lambda items: [updated if item["id"] == model_id else item for item in items])
        return self.public_model(updated, include_secret=True)

    def delete_model(self, model_id: str) -> None:
        self.store.update("models", [], lambda items: [item for item in items if item["id"] != model_id])
        self.store.update("user_models", [], lambda items: [item for item in items if item["model_id"] != model_id])

    def list_models(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        models = [item for item in self.store.read("models", []) if item.get("enabled")]
        if user.get("role") != "ADMIN":
            allowed = {item["model_id"] for item in self.store.read("user_models", []) if item["user_id"] == user["id"]}
            models = [item for item in models if item["id"] in allowed]
        return [self.public_model(item) for item in models]

    @staticmethod
    def public_model(item: Dict[str, Any], include_secret: bool = False) -> Dict[str, Any]:
        result = {key: item.get(key, "") for key in ("id", "name", "provider", "model", "base_url", "enabled", "created_at")}
        result["api_key_set"] = bool(item.get("api_key"))
        if include_secret:
            result["api_key_preview"] = (item.get("api_key", "")[:4] + "…") if item.get("api_key") else "未设置"
        return result

    def assign_model(self, user_id: str, model_id: str) -> None:
        if not any(item["id"] == model_id for item in self.store.read("models", [])):
            raise KeyError("model not found")
        self.store.update("user_models", [], lambda items: items if any(item["user_id"] == user_id and item["model_id"] == model_id for item in items) else items + [{"user_id": user_id, "model_id": model_id}])

    def select_model(self, user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
        available = {item["id"]: item for item in self.list_models(user)}
        if model_id not in available:
            raise ValueError("该模型未分配给当前用户")
        self.store.update("users", [], lambda users: [dict(item, selected_model_id=model_id) if item["id"] == user["id"] else item for item in users])
        user["selected_model_id"] = model_id
        return available[model_id]

    def selected_model(self, user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        available = self.list_models(user)
        selected = user.get("selected_model_id")
        explicit = next((item for item in available if item["id"] == selected), None)
        if explicit:
            return explicit
        # Registration predates model setup. Prefer a usable assigned provider
        # over the bootstrap demo, without overriding an explicit selection.
        configured = next((item for item in available
                           if item.get("provider") not in ("local", "", None)
                           and item.get("base_url") and item.get("api_key_set")), None)
        return configured or (available[0] if available else None)

    def model_config(self, user: Dict[str, Any], model_id: str) -> Dict[str, Any]:
        """Return the selected model's private provider settings after access checks."""
        selected = next((item for item in self.store.read("models", []) if item.get("id") == model_id and item.get("enabled")), None)
        if not selected:
            raise ValueError("模型不存在或已停用")
        if user.get("role") != "ADMIN":
            allowed = any(item.get("user_id") == user.get("id") and item.get("model_id") == model_id for item in self.store.read("user_models", []))
            if not allowed:
                raise PermissionError("该模型未分配给当前用户")
        return dict(selected)

    def consume(self, user_id: str, model_id: str, request_id: str = "") -> Dict[str, Any]:
        # Keep the balance decrement and usage journal in one process/file lock.
        # request_id makes retries from the task runner idempotent.
        with self.store._write_lock():
            usages = self.store.read("usage", [])
            if request_id:
                previous = next((item for item in usages
                                 if item.get("user_id") == user_id and item.get("request_id") == request_id), None)
                if previous:
                    return previous
            users = self.store.read("users", [])
            user = next((item for item in users if item["id"] == user_id), None)
            if not user:
                raise ValueError("用户不存在")
            if int(user.get("balance", 0)) < 1:
                raise ValueError("积分余额不足，请联系管理员充值")
            updated_user = dict(user, balance=int(user.get("balance", 0)) - 1)
            updated_users = [updated_user if item["id"] == user_id else item for item in users]
            if hasattr(self.store, "_request"):
                self.store._request("PUT", "users", updated_users)
            else:
                self.store._write("users", updated_users)
            record = {"id": new_id("use"), "user_id": user_id, "model_id": model_id,
                      "request_id": request_id, "cost": 1, "created_at": now_iso()}
            updated_usage = usages + [record]
            if hasattr(self.store, "_request"):
                self.store._request("PUT", "usage", updated_usage)
            else:
                self.store._write("usage", updated_usage)
            return record

    def usage(self, user_id: str) -> Dict[str, Any]:
        records = [item for item in self.store.read("usage", []) if item["user_id"] == user_id]
        return {"total_calls": len(records), "total_cost": sum(int(item.get("cost", 1)) for item in records), "items": records[-100:]}

    def credit(self, user_id: str, amount: int) -> Dict[str, Any]:
        if not 1 <= int(amount) <= 1_000_000:
            raise ValueError("充值积分需在 1-1000000 之间")
        def update(users):
            for item in users:
                if item["id"] == user_id:
                    updated = dict(item, balance=int(item.get("balance", 0)) + int(amount))
                    return [updated if old["id"] == user_id else old for old in users]
            raise KeyError("user not found")
        updated = self.store.update("users", [], update)
        user = next(item for item in updated if item["id"] == user_id)
        return self.public_user(user)
