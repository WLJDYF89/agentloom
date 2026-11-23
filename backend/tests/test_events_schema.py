from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.events import (
    EVENT_TYPES,
    SCHEMA_VERSION,
    Actor,
    ApprovalGranted,
    ApprovalRejected,
    ApprovalRequested,
    ErrorKind,
    ErrorRaised,
    EventBase,
    RunFinished,
    RunResumed,
    RunStarted,
    RunStatus,
    StepFinished,
    StepStarted,
    ToolCompleted,
    ToolDecision,
    ToolFailed,
    ToolRequested,
    canonical_json,
    new_event_id,
    parse_event,
    parse_event_json,
)
from pydantic import ValidationError

TRACE = "5888caede20946f4a54ce913d7401552"


def envelope(type_: str, seq: int = 1, actor: Actor = Actor.AGENT) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": new_event_id(),
        "run_id": "run_01HQZ9X2",
        "seq": seq,
        "type": type_,
        "trace_id": TRACE,
        "created_at": "2026-11-24T02:15:33.412Z",
        "actor": actor.value,
    }


SAMPLES: list[dict[str, Any]] = [
    {
        **envelope("run.started", 1, Actor.HUMAN),
        "task": "查一下工单 #1234 的进展，如果是超时状态就发邮件通知负责人",
        "model": "deepseek-chat",
        "max_steps": 20,
        "token_budget": None,
        "cost_budget_usd": None,
    },
    {
        **envelope("run.resumed", 8, Actor.SYSTEM),
        "reason": "restart",
        "from_seq": 7,
    },
    {
        **envelope("run.finished", 20, Actor.SYSTEM),
        "status": "succeeded",
        "reason": None,
        "steps_used": 5,
        "tokens_used": 3120,
        "cost_usd": 0.00182,
    },
    {**envelope("step.started", 2), "step_seq": 1, "attempt": 1},
    {
        **envelope("step.llm_response", 4),
        "step_seq": 2,
        "model": "deepseek-chat",
        "content": "先查工单状态。",
        "tool_calls": [
            {"call_id": "call_1", "tool_name": "get_ticket", "args": {"ticket_id": "1234"}}
        ],
        "finish_reason": "tool_calls",
        "tokens_prompt": 412,
        "tokens_completion": 38,
        "latency_ms": 1180,
        "cost_usd": 0.000214,
    },
    {**envelope("step.finished", 7), "step_seq": 2, "outcome": "continue"},
    {
        **envelope("tool.requested", 5),
        "step_seq": 2,
        "call_id": "call_1",
        "tool_name": "get_ticket",
        "args": {"ticket_id": "1234"},
        "normalized_args": {"ticket_id": "1234"},
        "idempotency_key": "9c1f2a7e5b3d8c4a6e0f2b1d9a8c7e5",
        "timeout_ms": 5000,
        "decision": "allow",
    },
    {
        **envelope("tool.completed", 6, Actor.TOOL),
        "step_seq": 2,
        "call_id": "call_1",
        "result": {"ticket_id": "1234", "status": "open", "updated_at": "2026-11-23T10:02:00Z"},
        "truncated": False,
        "duration_ms": 42,
    },
    {
        **envelope("tool.failed", 6, Actor.TOOL),
        "step_seq": 2,
        "call_id": "call_1",
        "error": {"kind": "tool_timeout", "message": "超过 5000ms 未返回", "retriable": True},
        "duration_ms": 5001,
    },
    {
        **envelope("approval.requested", 10),
        "step_seq": 4,
        "call_id": "call_3",
        "tool_name": "send_email",
        "args": {"to": "someone@corp.example", "subject": "工单 1234 超时"},
        "risk": "对外发送邮件，可能送错人",
    },
    {
        **envelope("approval.granted", 11, Actor.HUMAN),
        "step_seq": 4,
        "call_id": "call_3",
        "approver": "qianz",
        "args_override": {"to": "ops@corp.example", "subject": "工单 1234 超时"},
        "note": "收件人改成运维组",
    },
    {
        **envelope("approval.rejected", 11, Actor.HUMAN),
        "step_seq": 4,
        "call_id": "call_3",
        "approver": "qianz",
        "reason": "不该给外部发邮件",
    },
    {
        **envelope("error.raised", 9, Actor.SYSTEM),
        "kind": "schema_validation",
        "message": "参数 ticket_id 应为字符串，收到 1234",
        "retriable": True,
        "step_seq": 3,
        "call_id": "call_2",
        "context": {"field": "ticket_id", "expected": "string", "got": "integer"},
    },
]


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["type"])
def test_every_sample_round_trips(sample: dict[str, Any]) -> None:
    event = parse_event(sample)
    assert event.type == sample["type"]
    assert parse_event_json(event.model_dump_json()) == event
    assert parse_event(json.loads(canonical_json(event))) == event


def test_every_declared_type_has_a_sample() -> None:
    declared = {cls.model_fields["type"].default for cls in EVENT_TYPES}
    covered = {s["type"] for s in SAMPLES}
    assert declared == covered


def test_discriminator_picks_the_right_class() -> None:
    expected = {cls.model_fields["type"].default: cls for cls in EVENT_TYPES}
    for sample in SAMPLES:
        assert type(parse_event(sample)) is expected[sample["type"]]


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event({**envelope("run.exploded"), "task": "x", "model": "m"})


def test_events_are_frozen() -> None:
    event = parse_event(SAMPLES[0])
    assert isinstance(event, RunStarted)
    with pytest.raises(ValidationError):
        event.seq = 99  # type: ignore[misc]


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        parse_event({**SAMPLES[0], "whoops": 1})


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_event({**SAMPLES[0], "created_at": "2026-11-24T02:15:33.412000"})


def test_seq_must_start_at_one() -> None:
    with pytest.raises(ValidationError):
        parse_event({**SAMPLES[0], "seq": 0})


def test_defaults_fill_in() -> None:
    event = parse_event(
        {
            "run_id": "run_1",
            "seq": 1,
            "type": "run.started",
            "trace_id": TRACE,
            "actor": "human",
            "task": "t",
            "model": "m",
        }
    )
    assert isinstance(event, RunStarted)
    assert event.schema_version == 1
    assert event.max_steps == 20
    assert len(event.event_id) == 32
    assert event.created_at.tzinfo is not None


class TestCanonicalJson:
    def test_byte_identical_for_equal_events(self) -> None:
        event = parse_event(SAMPLES[4])
        assert canonical_json(event) == canonical_json(parse_event(SAMPLES[4]))

    def test_keys_are_sorted(self) -> None:
        raw = canonical_json(parse_event(SAMPLES[0]))
        keys = list(json.loads(raw).keys())
        assert keys == sorted(keys)

    def test_uses_compact_separators(self) -> None:
        raw = canonical_json(parse_event(SAMPLES[0]))
        expected = json.dumps(
            json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        assert raw == expected

    def test_datetime_is_utc_z_with_millis(self) -> None:
        payload = json.loads(canonical_json(parse_event(SAMPLES[0])))
        assert payload["created_at"] == "2026-11-24T02:15:33.412Z"

    def test_non_utc_input_normalises_to_utc(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        local = datetime(2026, 11, 24, 10, 15, 33, 412000, tzinfo=shanghai)
        event = parse_event({**SAMPLES[0], "created_at": local})
        payload = json.loads(canonical_json(event))
        assert payload["created_at"] == "2026-11-24T02:15:33.412Z"

    def test_chinese_is_not_escaped(self) -> None:
        raw = canonical_json(parse_event(SAMPLES[0]))
        assert "查一下工单" in raw

    def test_null_is_preserved_not_dropped(self) -> None:
        payload = json.loads(canonical_json(parse_event(SAMPLES[0])))
        assert "token_budget" in payload
        assert payload["token_budget"] is None

    def test_different_payload_gives_different_json(self) -> None:
        a = canonical_json(parse_event(SAMPLES[0]))
        b = canonical_json(parse_event({**SAMPLES[0], "task": "另一件事"}))
        assert a != b


class TestFieldConstraints:
    def test_step_seq_positive(self) -> None:
        with pytest.raises(ValidationError):
            parse_event({**envelope("step.started"), "step_seq": 0})

    def test_timeout_positive(self) -> None:
        with pytest.raises(ValidationError):
            parse_event({**SAMPLES[6], "timeout_ms": 0})

    def test_negative_token_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_event({**SAMPLES[4], "tokens_prompt": -1})

    def test_bad_enum_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_event({**SAMPLES[6], "decision": "maybe"})

    def test_decision_covers_all_three(self) -> None:
        assert {d.value for d in ToolDecision} == {"allow", "needs_approval", "deny"}

    def test_run_status_covers_all_four_terminations(self) -> None:
        assert {s.value for s in RunStatus} >= {
            "succeeded",
            "failed",
            "stopped_max_steps",
            "stopped_budget",
            "stopped_consecutive_failures",
        }


def test_tool_call_without_result_means_in_flight() -> None:
    """A21 的三态判定就建立在这个结构差异上。"""
    requested = parse_event(SAMPLES[6])
    assert isinstance(requested, ToolRequested)
    assert requested.call_id == "call_1"

    completed = parse_event(SAMPLES[7])
    failed = parse_event(SAMPLES[8])
    assert isinstance(completed, ToolCompleted)
    assert isinstance(failed, ToolFailed)
    assert completed.call_id == failed.call_id == requested.call_id


def test_denied_call_has_no_result_event() -> None:
    denied = parse_event({**SAMPLES[6], "decision": "deny"})
    assert isinstance(denied, ToolRequested)
    assert denied.decision is ToolDecision.DENY


def test_all_models_share_the_envelope() -> None:
    required = {"schema_version", "event_id", "run_id", "seq", "type", "trace_id", "created_at"}
    for cls in EVENT_TYPES:
        assert required <= set(cls.model_fields), cls.__name__
        assert issubclass(cls, EventBase)


def test_class_hierarchy_covers_the_five_type_prefixes() -> None:
    """六族事件里 run 族含 run.started/resumed/finished，故前缀是 5 个。"""
    families = {cls.model_fields["type"].default.split(".")[0] for cls in EVENT_TYPES}
    assert families == {"run", "step", "tool", "approval", "error"}


def test_enums_are_strings_on_the_wire() -> None:
    event = parse_event(SAMPLES[2])
    assert isinstance(event, RunFinished)
    payload = json.loads(canonical_json(event))
    assert payload["status"] == "succeeded"
    assert payload["actor"] == "system"


def test_error_kind_matches_documented_set() -> None:
    assert {k.value for k in ErrorKind} == {
        "llm_error",
        "tool_timeout",
        "schema_validation",
        "policy_denied",
        "internal",
    }


def test_approval_records_who_and_what() -> None:
    granted = parse_event(SAMPLES[10])
    assert isinstance(granted, ApprovalGranted)
    assert granted.approver == "qianz"
    assert granted.args_override == {"to": "ops@corp.example", "subject": "工单 1234 超时"}
    assert granted.created_at.tzinfo is not None

    rejected = parse_event(SAMPLES[11])
    assert isinstance(rejected, ApprovalRejected)
    assert rejected.reason


@pytest.mark.parametrize(
    "cls",
    [ApprovalRequested, ErrorRaised, RunResumed, StepStarted, StepFinished],
)
def test_sparse_types_still_serialise(cls: type[EventBase]) -> None:
    sample = next(s for s in SAMPLES if parse_event(s).__class__ is cls)
    assert parse_event_json(canonical_json(parse_event(sample))) == parse_event(sample)
