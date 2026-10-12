import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


TOOL_API_VERSION = "1.0"


def new_request_id() -> str:
    return "call_%s" % uuid.uuid4().hex[:12]


@dataclass
class ToolRequest:
    """The single wire format used by every Agent tool invocation."""

    tool: str
    action: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    workspace_id: str = ""
    request_id: str = field(default_factory=new_request_id)
    api_version: str = TOOL_API_VERSION
    approval: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ToolRequest":
        if payload.get("api_version", TOOL_API_VERSION) != TOOL_API_VERSION:
            raise ValueError("unsupported tool api version")
        if not payload.get("tool") or not payload.get("action"):
            raise ValueError("tool and action are required")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        approval = payload.get("approval", {})
        if not isinstance(approval, dict):
            raise ValueError("approval must be an object")
        if type(approval.get("approved", False)) is not bool:
            raise ValueError("approval.approved must be a boolean")
        return cls(
            tool=str(payload["tool"]),
            action=str(payload["action"]),
            arguments=arguments,
            task_id=str(payload.get("task_id", "")),
            workspace_id=str(payload.get("workspace_id", "")),
            request_id=str(payload.get("request_id") or new_request_id()),
            api_version=TOOL_API_VERSION,
            approval=approval,
        )

    @property
    def approved(self) -> bool:
        value = self.approval.get("approved", False)
        if type(value) is not bool:
            raise ValueError("approval.approved must be a boolean")
        return value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResponse:
    request_id: str
    ok: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    api_version: str = TOOL_API_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
