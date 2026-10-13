from typing import Any, Dict


DEFAULT_MODEL_SETTINGS = {
    "provider": "local",
    "model": "deterministic-mvp",
    "base_url": "",
    "api_key": "",
    "temperature": 0.2,
    "max_tokens": 4096,
}


class SettingsService:
    """Stores global model configuration and never returns the raw API key."""

    def __init__(self, store: Any):
        self.store = store

    def _raw(self) -> Dict[str, Any]:
        current = dict(DEFAULT_MODEL_SETTINGS)
        current.update(self.store.read("settings", {}))
        return current

    def public(self) -> Dict[str, Any]:
        current = self._raw()
        api_key = current.get("api_key", "")
        return {
            "provider": current["provider"],
            "model": current["model"],
            "base_url": current["base_url"],
            "temperature": current["temperature"],
            "max_tokens": current["max_tokens"],
            "api_key_set": bool(api_key),
            "api_key_preview": (api_key[:4] + "…" + api_key[-4:]) if len(api_key) > 8 else ("已设置" if api_key else "未设置"),
        }

    def update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self._raw()
        provider = str(payload.get("provider", current["provider"])).strip().lower()
        if provider not in ("openai", "anthropic", "google", "local", "custom"):
            raise ValueError("unsupported model provider")
        model = str(payload.get("model", current["model"])).strip()
        if not model:
            raise ValueError("model cannot be empty")
        current["provider"] = provider
        current["model"] = model
        current["base_url"] = str(payload.get("base_url", current["base_url"])).strip()
        current["temperature"] = max(0.0, min(2.0, float(payload.get("temperature", current["temperature"]))))
        current["max_tokens"] = max(1, min(128000, int(payload.get("max_tokens", current["max_tokens"]))))
        if payload.get("clear_api_key"):
            current["api_key"] = ""
        elif "api_key" in payload and str(payload.get("api_key", "")).strip():
            current["api_key"] = str(payload["api_key"]).strip()
        self.store.write("settings", current)
        return self.public()
