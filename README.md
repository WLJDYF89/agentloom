# agentloom

> 可恢复的 Agent 执行内核。
>
> 一句话说清它要回答的问题：**这个 Agent 能不能安全跑完一件多步任务，中途挂了能不能接着跑，副作用会不会重复。**

---

## 为什么不用微服务

这是本项目的第一个技术决策，也是被问得最多的一个，所以放在最前面。

agentloom 的核心能力是「**把一次多步 Agent 执行变成一条可重放的事件流**」。这条链路上，
几乎每一个关键动作都是**跨模块的强一致操作**：

| 关键动作 | 涉及的状态 | 如果是微服务 |
| --- | --- | --- |
| 追加一条事件 | 事件表 + 该 run 的序号（seq） | 要么两段提交，要么靠分布式锁；**seq 连续递增**直接没了 |
| 工具调用前落幂等键 | 幂等表 + 事件表 | 幂等键写成功但事件没写 → 恢复时判重判错 |
| 生成检查点 | 当前事件流的快照 + 待审批队列 | 快照与队列不同步 → 恢复出「幽灵审批」 |
| 人工审批后继续 | 审批记录 + 检查点 + 事件 seq | 三处状态，任意一处失败都要写补偿逻辑 |

这些操作全部落在**同一个 PostgreSQL 事务**里就能天然正确：一条 `BEGIN ... COMMIT` 同时写事件、
写幂等键、写快照，要么全成要么全败。拆成服务以后，这个「天然正确」会立刻变成一套自研的
saga / 补偿 / 对账机制——那是**用分布式系统的复杂度，换一个本来不存在的一致性问题**。

第二个理由更直接：本项目的**全部价值都在状态机与恢复逻辑上**，不在服务治理上。单体能跑通
「12/12 中断点恢复一致」，拆成微服务只会让这条验收更难达成，而不是更容易。

第三个理由是**规模**。总工期 220h、单一团队、单机 Docker Compose 部署。微服务带来的独立部署、
独立扩缩容、技术栈隔离，在这里一个都用不上。

所以：**单一后端，单体进程，但内部按模块分层**（`api` / `core` / `domain` / `storage` 等），
模块之间靠明确的接口边界通信。等真的出现「某个模块必须独立扩容」的证据，再拆不迟——
那时候的拆分也是有依据的拆分，而不是提前押注。

---

## 技术栈

**后端**：Python 3.12 · FastAPI · Pydantic v2 · PostgreSQL 16 · MCP SDK
**前端**：Vue 3 · Vite · TypeScript · Element Plus（A08 阶段开工）

选 Python 是因为 MCP SDK 与主流 Agent 生态在 Python 侧最完整；选 FastAPI 是因为事件流与
流式推送（SSE）需要原生异步；选 PostgreSQL 是因为本项目同时需要**事务**、**唯一索引**
（事件 seq 与幂等键都靠它兜底）和 **JSONB**（事件 payload 天然是半结构化数据）。

---

## 目录结构

```
agentloom/
├── backend/          FastAPI 服务（唯一后端进程）
│   ├── app/
│   │   ├── core/     配置、错误码、日志、trace_id —— 不依赖任何业务
│   │   ├── api/      路由层，只做协议转换
│   │   └── main.py   应用装配：中间件、异常处理、生命周期
│   ├── Dockerfile    镜像定义（放在这里，让 build context 与它同目录）
│   └── pyproject.toml  依赖 / ruff / mypy / pytest 全部集中在这里
├── frontend/         Vue3 控制台（A08 起）
├── deploy/           Docker Compose 编排与 PostgreSQL 初始化 SQL
├── docs/             排期表、事件模型、设计文档
├── scripts/          运维 / 数据生成 / 故障注入脚本
├── Makefile          标准入口（Linux / macOS / CI / 容器内）
├── make.ps1          Windows 等价入口（目标一一对应）
└── make.cmd          Windows 短命令：make lint
```

---

## 快速开始

### Windows（本机没有 GNU make）

```bat
make setup      :: 建 venv + 装依赖（首次）
make lint
make test
make check      :: lint + typecheck + test
```

`make.cmd` 只是转发到 `powershell -File make.ps1 %*`，目标名与 Makefile 完全一致。
脚本以 UTF-8 **with BOM** 保存——Windows PowerShell 5.1 在无 BOM 时按 ANSI 代码页解析，
中文注释会把脚本解坏。

### Linux / macOS / CI

```sh
make setup
make lint
make test
```

两个入口的目标必须保持一一对应：`setup / venv / deps / lint / format / typecheck /
test / test-cov / check / run / up / up-build / down / logs / ps / clean`。

### 直接跑服务

```sh
make run          # 等价于 cd backend && .venv/bin/python -m app
curl http://127.0.0.1:8000/health
```

OpenAPI 文档在 <http://127.0.0.1:8000/docs>。

### 起全栈（Docker）

```sh
make up           # postgres:16 + backend，等到两者都 healthy 才返回
curl http://localhost:8000/health
make ps           # 看容器与健康状态
make down         # 停容器，保留数据卷
```

`make up` 内部是 `docker compose -f deploy/docker-compose.yml up -d --wait`。**`--wait` 是
这条验收标准的关键**：不加它 `up -d` 会立刻返回 0，哪怕容器两秒后就崩了；加了它，命令
返回 0 就等于所有 healthcheck 都通过了。改了 Dockerfile 或依赖后改用 `make up-build`。

端口、初始化 SQL 的执行时机、两份数据库地址的区别，见 [deploy/README.md](deploy/README.md)。

---

## 工程约定

- **配置只从环境变量读**，前缀 `AGENTLOOM_`，见 [.env.example](.env.example)。`Settings` 是
  frozen 的，避免运行期被偷偷改掉。
- **所有错误响应长一个样**：`{code, message, trace_id, details?}`。业务异常抛 `AppError`，
  不允许裸 `HTTPException(500)`。
- **每个请求都有 trace_id**：客户端可传 `X-Trace-Id`，不传则服务生成，并回写到响应头；
  日志格式里带该字段，出问题能一句话定位。
- **ruff 与 mypy 都是 strict**，`pytest` 把 warning 当错误（`filterwarnings = error`）。
  这些不是为了好看，是为了让「坏掉的代码提交不进来」。

---

## 定位说明

这份 README 面向工程师。项目在**不同场合该用什么措辞**（简历 / 面试 / 技术文档各一套），
以及「这不就是把 LangGraph 重写了一遍吗」该怎么回答，统一记在
[docs/项目定位.md](docs/项目定位.md)。写 README、写讲稿时从那里取材。

---

## 当前进度

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 环境与骨架（A01 仓库结构 + 工具链 · A02 Docker Compose 全栈） | 已完成 |
| P1 | 事件模型与持久化 | 待开始 |
| … | 详见 [docs/排期表_A_agentloom.xlsx](docs/排期表_A_agentloom.xlsx) | |

项目范围与边界、和 LangGraph / Temporal 的差异、待验证的指标口径，写在
[docs/项目定位.md](docs/项目定位.md)。
