import json
import os
import re
from urllib import error as urlerror
from urllib import request as urlrequest
from typing import Any, Dict


class ModelGateway:
    """Provider-neutral model contract.

    The local deterministic planner remains the safe default. When a global
    compatible-mode configuration has a base URL and key, ``plan`` sends the
    same structured contract to ``/chat/completions`` and validates the model
    response before it reaches the task manager.
    """

    def __init__(self, settings: Any = None):
        self.settings = settings

    def config(self) -> Dict[str, Any]:
        return self.settings.public() if self.settings else {"provider": "local", "model": "deterministic-mvp", "api_key_set": False}

    @staticmethod
    def validate_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce the structured model contract before a task is persisted."""
        if turn.get("schema") != "agent.turn/v1":
            raise ValueError("model response must use agent.turn/v1")
        for field in ("thinking", "steps", "tool_calls", "patches"):
            if not isinstance(turn.get(field), list):
                raise ValueError("model response field %s must be an array" % field)
        for item in turn["thinking"]:
            if not all(key in item for key in ("id", "title", "summary", "status")):
                raise ValueError("thinking item is missing required fields")
        for item in turn["tool_calls"]:
            if not all(key in item for key in ("tool", "action", "arguments")):
                raise ValueError("tool call is missing required fields")
        return turn

    def plan(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        settings = self.settings._raw() if self.settings and hasattr(self.settings, "_raw") else {}
        if settings.get("base_url") and settings.get("api_key") and settings.get("provider") not in ("local", ""):
            return self._remote_plan(goal, context, settings)
        return self.validate_turn({
            "schema": "agent.turn/v1",
            "summary": goal,
            "thinking": [
                {"id": "understand", "title": "理解需求", "summary": "识别用户目标、工程范围和需要验证的结果", "status": "pending"},
                {"id": "plan", "title": "制定步骤", "summary": "按工程类型定位代码、执行变更并运行验证", "status": "pending"},
            ],
            "steps": [
                {"step": 1, "title": "理解工作区", "action": "code.index", "detail": "读取工程类型、文件和相关符号"},
                {"step": 2, "title": "执行用户目标", "action": "workspace.apply_patch", "detail": goal},
                {"step": 3, "title": "验证结果", "action": "process.run", "detail": "根据工程类型运行测试或检查命令"},
            ],
            "tool_calls": [],
            "patches": [],
        })

    def _remote_plan(self, goal: str, context: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        base_url = str(settings.get("base_url", "")).rstrip("/")
        endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
        system = (
            "You are CodeSpider's code engineering agent. Return only one valid JSON object, "
            "without Markdown fences or extra text. Use this exact schema: "
            '{"schema":"agent.turn/v1","summary":"string","thinking":[{"id":"string",'
            '"title":"string","summary":"string","status":"pending"}],'
            '"steps":[{"step":1,"title":"string","action":"string","detail":"string"}],'
            '"tool_calls":[{"tool":"string","action":"string","arguments":{}}],'
            '"patches":[{"path":"string","expected":"string","replacement":"string"}]}. '
            "Do not invent tool results. Keep patches empty when no exact edit is justified."
        )
        user = json.dumps({"goal": goal, "context": context}, ensure_ascii=False)
        payload = {
            "model": settings.get("model", ""),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": float(settings.get("temperature", 0.2)),
            "max_tokens": int(settings.get("max_tokens", 4096)),
            "response_format": {"type": "json_object"},
        }
        request = urlrequest.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + str(settings["api_key"])},
            method="POST",
        )
        timeout = max(5, min(180, int(os.environ.get("CODESPIDER_MODEL_TIMEOUT", "90"))))
        try:
            with urlrequest.urlopen(request, timeout=timeout) as response:
                raw = response.read(8 * 1024 * 1024).decode("utf-8")
        except urlerror.HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise RuntimeError("model API returned HTTP %s: %s" % (exc.code, detail[:400]))
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("model API request failed: %s" % exc)
        try:
            response_json = json.loads(raw)
            content = response_json["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
            if not isinstance(content, str):
                raise ValueError("message content is not text")
            # Be tolerant of a provider adding a fence despite the prompt.
            fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
            candidate = fenced.group(1) if fenced else content.strip()
            turn = json.loads(candidate)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("model response was not valid agent.turn JSON: %s" % exc)
        return self.validate_turn(turn)
