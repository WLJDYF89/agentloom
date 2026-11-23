"""开发服务器入口：``python -m app`` 或 ``uvicorn app.main:app``。"""

from __future__ import annotations

import uvicorn

from app.core.config import get_settings
from app.main import create_app

app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "local",
        log_config=None,  # 复用 app.core.logging 的配置
    )


if __name__ == "__main__":
    main()
