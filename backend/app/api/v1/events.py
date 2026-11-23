from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import ERROR_RESPONSES
from app.core.errors import AppError, ErrorCode
from app.events import EVENT_TYPES, SCHEMA_VERSION, EventBase, canonical_json, parse_event

router = APIRouter(prefix="/events", tags=["events"])

_BY_NAME: dict[str, type[EventBase]] = {
    cls.model_fields["type"].default: cls for cls in EVENT_TYPES
}


class EventTypesResponse(BaseModel):
    schema_version: int
    types: list[str] = Field(description="当前代码认识的事件类型")


class CanonicalizeRequest(BaseModel):
    event: dict[str, Any] = Field(description="一条事件的 JSON 表示")


class CanonicalizeResponse(BaseModel):
    type: str
    canonical: str = Field(description="规范化后的 JSON 串，A07 的状态 hash 建立在这上面")
    seq: int
    run_id: str


@router.get(
    "/types",
    response_model=EventTypesResponse,
    summary="列出事件类型",
    responses=ERROR_RESPONSES,
)
async def list_event_types() -> EventTypesResponse:
    return EventTypesResponse(schema_version=SCHEMA_VERSION, types=sorted(_BY_NAME))


@router.post(
    "/canonicalize",
    response_model=CanonicalizeResponse,
    summary="校验一条事件并给出规范化 JSON",
    responses=ERROR_RESPONSES,
)
async def canonicalize(payload: CanonicalizeRequest = Body()) -> CanonicalizeResponse:
    try:
        event = parse_event(payload.event)
    except ValidationError as exc:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "事件不符合 schema",
            details={"errors": exc.errors(include_url=False)},
        ) from exc

    return CanonicalizeResponse(
        type=event.type,
        canonical=canonical_json(event),
        seq=event.seq,
        run_id=event.run_id,
    )


@router.get(
    "/{event_type}/schema",
    summary="取某一事件类型的 JSON Schema",
    responses=ERROR_RESPONSES,
)
async def event_schema(event_type: str) -> dict[str, Any]:
    cls = _BY_NAME.get(event_type)
    if cls is None:
        raise AppError(
            ErrorCode.NOT_FOUND,
            f"未知事件类型 {event_type}",
            details={"known": sorted(_BY_NAME)},
        )
    schema: dict[str, Any] = cls.model_json_schema()
    return schema
