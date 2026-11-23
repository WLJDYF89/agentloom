"""A01 验收：服务骨架能起来，健康检查与统一错误格式成立。"""

from __future__ import annotations

from app.main import TRACE_HEADER
from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    """/health 返回 200 —— 排期表里写明的验收点。"""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "agentloom"
    assert body["environment"] == "test"
    assert body["version"]


def test_health_echoes_trace_id(client: TestClient) -> None:
    """响应头必须带 trace_id，调用方能拿它去日志里对齐。"""
    response = client.get("/health", headers={TRACE_HEADER: "abc123"})

    assert response.headers[TRACE_HEADER] == "abc123"


def test_trace_id_generated_when_absent(client: TestClient) -> None:
    """不传 trace_id 时由服务端生成，不能为空。"""
    response = client.get("/health")

    assert len(response.headers[TRACE_HEADER]) == 32


def test_404_uses_structured_error(client: TestClient) -> None:
    """不存在的路径也必须是 {code, message, trace_id}，不能裸 404 页。"""
    response = client.get("/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["message"]
    assert body["trace_id"] == response.headers[TRACE_HEADER]


def test_openapi_is_served(client: TestClient) -> None:
    """OpenAPI 文档可用：面试演示要能打开 /docs。"""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "agentloom"
    assert "/health" in schema["paths"]


def test_module_level_asgi_app_exists() -> None:
    """`uvicorn app.main:app` 必须能导入到实例。

    这行曾经漏过：只有 ``create_app()`` 没有模块级 ``app``，uvicorn 启动后
    报 "Attribute app not found in module app.main"，而单测全绿——
    因为测试自己调的是工厂函数。这里把它钉死。
    """
    from app.main import app as asgi_app

    assert asgi_app.title == "agentloom"
