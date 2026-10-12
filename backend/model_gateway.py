from typing import Any, Dict, List


class ModelGateway:
    """Provider-neutral model contract.

    The MVP keeps this boundary deterministic so local development does not
    require an API key. A provider adapter can later implement ``plan`` and
    return the same structured task plan and patch format.
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
