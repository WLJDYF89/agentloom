from __future__ import annotations

from typing import Any

import pytest
from app.core.errors import AppError, ErrorCode
from app.main import API_PREFIX, TRACE_HEADER, create_app
from fastapi.testclient import TestClient


class TestRouteLayering:
    def test_ops_routes_are_unprefixed(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200
        assert client.get("/version").status_code == 200

    def test_business_routes_live_under_v1(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/events/types").status_code == 200

    def test_v1_does_not_expose_ops(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/health").status_code == 404

    def test_openapi_lists_both_layers(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/health" in paths
        assert "/version" in paths
        assert f"{API_PREFIX}/events/types" in paths

    def test_openapi_tags_are_declared(self, client: TestClient) -> None:
        tags = {t["name"] for t in client.get("/openapi.json").json()["tags"]}
        assert {"ops", "events"} <= tags

    def test_every_route_states_its_error_shape(self, client: TestClient) -> None:
        """所有接口都要在 OpenAPI 里声明错误响应，前端才能照契约接。"""
        paths = client.get("/openapi.json").json()["paths"]
        for path, methods in paths.items():
            for method, spec in methods.items():
                if method == "parameters":
                    continue
                assert "responses" in spec, f"{method.upper()} {path} 没声明响应"
                assert "422" in spec["responses"], f"{method.upper()} {path} 缺 422"


class TestEventEndpoints:
    def test_types_returns_all_thirteen(self, client: TestClient) -> None:
        body = client.get(f"{API_PREFIX}/events/types").json()
        assert body["schema_version"] == 1
        assert len(body["types"]) == 13
        assert "run.started" in body["types"]
        assert "tool.requested" in body["types"]

    def test_types_are_sorted(self, client: TestClient) -> None:
        types = client.get(f"{API_PREFIX}/events/types").json()["types"]
        assert types == sorted(types)

    def test_canonicalize_round_trip(self, client: TestClient) -> None:
        payload = {
            "event": {
                "run_id": "run_1",
                "seq": 1,
                "type": "run.started",
                "trace_id": "t" * 32,
                "actor": "human",
                "created_at": "2026-11-24T02:15:33.412Z",
                "event_id": "e" * 32,
                "task": "查工单",
                "model": "deepseek-chat",
            }
        }
        body = client.post(f"{API_PREFIX}/events/canonicalize", json=payload).json()
        assert body["type"] == "run.started"
        assert body["seq"] == 1
        assert body["run_id"] == "run_1"
        assert body["canonical"].startswith("{")
        assert "查工单" in body["canonical"]

    def test_canonicalize_is_stable(self, client: TestClient) -> None:
        payload = {
            "event": {
                "run_id": "run_1",
                "seq": 1,
                "type": "run.started",
                "trace_id": "t" * 32,
                "actor": "human",
                "created_at": "2026-11-24T02:15:33.412Z",
                "event_id": "e" * 32,
                "task": "x",
                "model": "m",
            }
        }
        first = client.post(f"{API_PREFIX}/events/canonicalize", json=payload).json()
        second = client.post(f"{API_PREFIX}/events/canonicalize", json=payload).json()
        assert first["canonical"] == second["canonical"]

    def test_canonicalize_rejects_bad_event(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/events/canonicalize",
            json={"event": {"type": "nope"}},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_FAILED"
        assert body["details"]["errors"]

    def test_schema_endpoint(self, client: TestClient) -> None:
        schema = client.get(f"{API_PREFIX}/events/run.started/schema").json()
        assert schema["title"] == "RunStarted"
        assert "task" in schema["properties"]

    def test_schema_of_unknown_type_is_404(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/events/run.exploded/schema")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "NOT_FOUND"
        assert body["details"]["known"]

    def test_schema_covers_all_types(self, client: TestClient) -> None:
        types = client.get(f"{API_PREFIX}/events/types").json()["types"]
        for type_ in types:
            assert client.get(f"{API_PREFIX}/events/{type_}/schema").status_code == 200


class TestErrorContract:
    """错误响应必须是 {code, message, trace_id}，绝不裸 500。"""

    def test_app_error_is_structured(self) -> None:
        app = create_app()

        @app.get("/_boom")
        async def boom() -> None:
            raise AppError(ErrorCode.CONFLICT, "run 已被占用", details={"run_id": "r1"})

        with TestClient(app) as c:
            response = c.get("/_boom")

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "CONFLICT"
        assert body["message"] == "run 已被占用"
        assert body["details"] == {"run_id": "r1"}
        assert body["trace_id"] == response.headers[TRACE_HEADER]

    def test_unexpected_exception_never_leaks_stack(self) -> None:
        app = create_app()

        @app.get("/_crash")
        async def crash() -> None:
            raise RuntimeError("数据库连接串 postgres://secret@host")

        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/_crash")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "INTERNAL_ERROR"
        assert body["message"] == "服务内部错误"
        assert "secret" not in response.text
        assert "Traceback" not in response.text
        assert "RuntimeError" not in response.text

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (400, "BAD_REQUEST"),
            (401, "UNAUTHORIZED"),
            (403, "FORBIDDEN"),
            (404, "NOT_FOUND"),
        ],
    )
    def test_framework_http_errors_use_the_same_shape(self, status: int, code: str) -> None:
        from fastapi import HTTPException

        app = create_app()

        @app.get(f"/_h{status}")
        async def raiser() -> None:
            raise HTTPException(status_code=status, detail="x")

        with TestClient(app) as c:
            response = c.get(f"/_h{status}")

        assert response.status_code == status
        body = response.json()
        assert body["code"] == code
        assert body["trace_id"] == response.headers[TRACE_HEADER]

    def test_error_body_model_matches_reality(self, client: TestClient) -> None:
        body: dict[str, Any] = client.get("/nope").json()
        assert set(body) <= {"code", "message", "trace_id", "details"}
        assert {"code", "message", "trace_id"} <= set(body)


class TestTracePropagation:
    def test_every_response_has_trace_id(self, client: TestClient) -> None:
        for path in ["/health", "/version", f"{API_PREFIX}/events/types", "/nope"]:
            response = client.get(path)
            assert TRACE_HEADER in response.headers, path

    def test_inbound_trace_id_wins(self, client: TestClient) -> None:
        response = client.get("/health", headers={TRACE_HEADER: "caller-supplied"})
        assert response.headers[TRACE_HEADER] == "caller-supplied"

    def test_error_body_trace_matches_header(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/events/nope.code/schema")
        assert response.json()["trace_id"] == response.headers[TRACE_HEADER]
