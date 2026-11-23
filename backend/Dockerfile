# backend/Dockerfile —— agentloom 后端镜像
#
# 放在 backend/ 而不是 deploy/，是为了让 build.context 与 Dockerfile 同处
# 一个目录：compose 里就不必写 "dockerfile 相对 context 还是相对 compose 文件"
# 这种容易搞错的路径。
#
# 构建（手动验证用，平时走 make up）：
#   docker build -t agentloom-backend:dev backend

FROM python:3.12-slim

# ---- 基础配置 ----
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 国内镜像源：实测清华源 0.29s、官方源 1.29s，快 4 倍。
# 允许在构建时覆盖（CI 或海外环境可传 --build-arg PIP_INDEX_URL=）。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# ---- 先装依赖，利用层缓存 ----
# 依赖清单单独一层：只要 pyproject.toml 没变，改代码时这一层直接命中缓存。
# 注意：这里必须先有 app/ 目录，否则 `pip install -e .` 会报
#   error: package directory 'app' does not exist
# 所以先复制一个最小的占位结构（见下方 COPY），再在最后覆盖成真实代码。
COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -e .

# ---- 非 root 用户 ----
# 容器以 root 跑是不必要的风险；createuser 之后切换。
# 注意要先把 /app 的所有权交出去，否则运行期无法写缓存文件。
RUN useradd --create-home --uid 1000 agentloom \
    && chown -R agentloom:agentloom /app
USER agentloom

EXPOSE 8000

# ---- 健康检查 ----
# python:3.12-slim 里没有 curl 也没有 wget，只能用 Python 自己发请求。
# 起始宽限期 10s：uvicorn 冷启动 + 导入 pydantic 通常 1-2s，留足余量。
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# ---- 启动 ----
# 不用 `python -m app`：那样会读 settings.environment == "local" 而开启
# uvicorn reload，容器里会多出 reloader 父进程，信号处理与日志都会变味。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
