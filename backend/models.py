from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


@dataclass
class Workspace:
    id: str
    name: str
    root: str
    project_type: str = "unknown"
    start_command: str = ""
    description: str = ""
    execution_mode: str = "safe"
    command_allowlist: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    id: str
    workspace_id: str
    goal: str
    status: str = "created"
    plan: List[Dict[str, Any]] = field(default_factory=list)
    patches: List[Dict[str, Any]] = field(default_factory=list)
    thinking: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_schema: str = "agent.turn/v1"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    error: Optional[str] = None
    workspace_snapshot: Dict[str, Any] = field(default_factory=dict)
    model_id: str = ""
    design: Dict[str, Any] = field(default_factory=dict)
    design_contract: Dict[str, Any] = field(default_factory=dict)
    design_review: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Event:
    id: str
    task_id: str
    sequence: int
    type: str
    payload: Dict[str, Any]
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
