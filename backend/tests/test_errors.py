"""错误码与业务异常的单元测试（不经过 HTTP）。"""

from __future__ import annotations

import pytest
from app.core.errors import AppError, ErrorCode


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (ErrorCode.BAD_REQUEST, 400),
        (ErrorCode.VALIDATION_FAILED, 422),
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.CONFLICT, 409),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.RATE_LIMITED, 429),
        (ErrorCode.INTERNAL_ERROR, 500),
        (ErrorCode.DEPENDENCY_UNAVAILABLE, 503),
    ],
)
def test_error_code_maps_to_http_status(code: ErrorCode, expected_status: int) -> None:
    assert AppError(code, "x").http_status == expected_status


def test_payload_carries_code_message_trace() -> None:
    err = AppError(ErrorCode.NOT_FOUND, "run 不存在", details={"run_id": "r1"})

    payload = err.to_payload("t-1")

    assert payload == {
        "code": "NOT_FOUND",
        "message": "run 不存在",
        "trace_id": "t-1",
        "details": {"run_id": "r1"},
    }


def test_details_omitted_when_empty() -> None:
    payload = AppError(ErrorCode.CONFLICT, "冲突").to_payload("t-2")

    assert "details" not in payload


def test_status_override_wins() -> None:
    err = AppError(ErrorCode.BAD_REQUEST, "x", status_override=418)

    assert err.http_status == 418
