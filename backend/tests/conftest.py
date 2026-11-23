"""共享的 pytest fixture。"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# 必须在导入 app 之前写入：配置对象在模块导入期就可能被构造。
# 环境变量优先级高于 .env，所以这里硬写的值一定生效，开发者本地的 .env
# 不会把测试带偏。
os.environ["AGENTLOOM_ENVIRONMENT"] = "test"
os.environ["AGENTLOOM_LOG_LEVEL"] = "WARNING"

from app.core.config import Settings, get_settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def settings() -> Settings:
    """测试专用配置。

    环境变量优先级高于 .env，所以上面硬写的两个值一定生效，
    开发者本地的 .env 不会把测试带偏。
    """
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """带生命周期钩子的 TestClient。"""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
