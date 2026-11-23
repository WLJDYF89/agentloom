from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
)

SCHEMA_VERSION: Final = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_event_id() -> str:
    """写入时用。replay 里不允许调用它，否则重放不再等价。"""
    return uuid.uuid4().hex


def _format_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcDatetime = Annotated[
    AwareDatetime,
    PlainSerializer(_format_utc, return_type=str, when_used="json"),
]


class Actor(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"
    HUMAN = "human"
    TOOL = "tool"


class RunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED_MAX_STEPS = "stopped_max_steps"
    STOPPED_BUDGET = "stopped_budget"
    STOPPED_CONSECUTIVE_FAILURES = "stopped_consecutive_failures"


class ErrorKind(StrEnum):
    LLM_ERROR = "llm_error"
    TOOL_TIMEOUT = "tool_timeout"
    SCHEMA_VALIDATION = "schema_validation"
    POLICY_DENIED = "policy_denied"
    INTERNAL = "internal"


class ToolDecision(StrEnum):
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    DENY = "deny"


class EventBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: str = Field(default_factory=new_event_id)
    run_id: str
    seq: int = Field(ge=1)
    trace_id: str
    created_at: UtcDatetime = Field(default_factory=_utcnow)
    actor: Actor


class RunStarted(EventBase):
    type: Literal["run.started"] = "run.started"
    task: str
    model: str
    max_steps: int = Field(default=20, ge=1)
    token_budget: int | None = None
    cost_budget_usd: float | None = None


class RunResumed(EventBase):
    type: Literal["run.resumed"] = "run.resumed"
    reason: Literal["restart", "approval_granted"]
    from_seq: int = Field(ge=0)


class RunFinished(EventBase):
    type: Literal["run.finished"] = "run.finished"
    status: RunStatus
    reason: str | None = None
    steps_used: int = Field(ge=0)
    tokens_used: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class StepStarted(EventBase):
    type: Literal["step.started"] = "step.started"
    step_seq: int = Field(ge=1)
    attempt: int = Field(default=1, ge=1)


class PlannedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class StepLLMResponse(EventBase):
    type: Literal["step.llm_response"] = "step.llm_response"
    step_seq: int = Field(ge=1)
    model: str
    content: str
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)
    finish_reason: str
    tokens_prompt: int = Field(ge=0)
    tokens_completion: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost_usd: float = Field(ge=0)


class StepFinished(EventBase):
    type: Literal["step.finished"] = "step.finished"
    step_seq: int = Field(ge=1)
    outcome: Literal["continue", "finish", "failed"]


class ToolRequested(EventBase):
    type: Literal["tool.requested"] = "tool.requested"
    step_seq: int = Field(ge=1)
    call_id: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    normalized_args: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    timeout_ms: int = Field(gt=0)
    decision: ToolDecision


class ToolError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    message: str
    retriable: bool = False


class ToolCompleted(EventBase):
    type: Literal["tool.completed"] = "tool.completed"
    step_seq: int = Field(ge=1)
    call_id: str
    result: Any = None
    truncated: bool = False
    duration_ms: int = Field(ge=0)


class ToolFailed(EventBase):
    type: Literal["tool.failed"] = "tool.failed"
    step_seq: int = Field(ge=1)
    call_id: str
    error: ToolError
    duration_ms: int = Field(ge=0)


class ApprovalRequested(EventBase):
    type: Literal["approval.requested"] = "approval.requested"
    step_seq: int = Field(ge=1)
    call_id: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    risk: str


class ApprovalGranted(EventBase):
    type: Literal["approval.granted"] = "approval.granted"
    step_seq: int = Field(ge=1)
    call_id: str
    approver: str
    args_override: dict[str, Any] | None = None
    note: str | None = None


class ApprovalRejected(EventBase):
    type: Literal["approval.rejected"] = "approval.rejected"
    step_seq: int = Field(ge=1)
    call_id: str
    approver: str
    reason: str


class ErrorRaised(EventBase):
    type: Literal["error.raised"] = "error.raised"
    kind: ErrorKind
    message: str
    retriable: bool = False
    step_seq: int | None = None
    call_id: str | None = None
    context: dict[str, Any] | None = None


Event = Annotated[
    RunStarted
    | RunResumed
    | RunFinished
    | StepStarted
    | StepLLMResponse
    | StepFinished
    | ToolRequested
    | ToolCompleted
    | ToolFailed
    | ApprovalRequested
    | ApprovalGranted
    | ApprovalRejected
    | ErrorRaised,
    Field(discriminator="type"),
]

EVENT_TYPES: Final[tuple[type[EventBase], ...]] = (
    RunStarted,
    RunResumed,
    RunFinished,
    StepStarted,
    StepLLMResponse,
    StepFinished,
    ToolRequested,
    ToolCompleted,
    ToolFailed,
    ApprovalRequested,
    ApprovalGranted,
    ApprovalRejected,
    ErrorRaised,
)

_ADAPTER: Final[TypeAdapter[Event]] = TypeAdapter(Event)  # type: ignore[arg-type]


def parse_event(data: Any) -> Event:
    return _ADAPTER.validate_python(data)


def parse_event_json(raw: str | bytes) -> Event:
    return _ADAPTER.validate_json(raw)


def canonical_json(event: EventBase) -> str:
    """A07 的状态 hash 建立在这上面：同一份数据必须序列化出同一串字节。"""
    return json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
