from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from app.events import EVENT_TYPES, canonical_json, parse_event

DOCS = Path(__file__).resolve().parents[2] / "docs" / "events.md"
BLOCK = re.compile(r"^### (\S+)\n\n```json\n(.*?)\n```", re.S | re.M)


def load_doc_samples() -> list[tuple[str, dict[str, Any]]]:
    return [(name, json.loads(body)) for name, body in BLOCK.findall(DOCS.read_text("utf-8"))]


SAMPLES = load_doc_samples()


def test_doc_has_samples() -> None:
    assert len(SAMPLES) == 6, [name for name, _ in SAMPLES]


@pytest.mark.parametrize(("heading", "payload"), SAMPLES, ids=[n for n, _ in SAMPLES])
def test_doc_sample_parses(heading: str, payload: dict[str, Any]) -> None:
    event = parse_event(payload)
    assert event.type == payload["type"]
    assert heading == payload["type"], "文档小节标题应与示例的 type 一致"


@pytest.mark.parametrize(("_heading", "payload"), SAMPLES, ids=[n for n, _ in SAMPLES])
def test_doc_sample_survives_canonical_round_trip(_heading: str, payload: dict[str, Any]) -> None:
    event = parse_event(payload)
    again = parse_event(json.loads(canonical_json(event)))
    assert again == event


def test_doc_uses_declared_event_types() -> None:
    declared = {cls.model_fields["type"].default for cls in EVENT_TYPES}
    for heading, _ in SAMPLES:
        assert heading in declared


def test_doc_samples_have_utc_timestamps() -> None:
    for heading, payload in SAMPLES:
        assert str(payload["created_at"]).endswith("Z"), heading
