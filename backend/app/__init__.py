"""agentloom 后端应用包。

可恢复的 Agent 执行内核：事件溯源驱动、幂等副作用防护、崩溃后可恢复。
"""

from importlib.metadata import PackageNotFoundError, version

try:  # pragma: no cover - 未以包形式安装时走 fallback
    __version__ = version("agentloom-backend")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0"

__all__ = ["__version__"]
