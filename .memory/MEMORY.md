# 项目记忆 · agentloom

| 项 | 值 |
| --- | --- |
| 路径 | `E:\002-my-agent\agentloom` |
| 类型 | Python 3.12 后端（FastAPI + Pydantic v2 + PostgreSQL）+ Vue3 前端（Vite + TS + Element Plus） |
| 包管理 | 后端 pip/venv，前端 pnpm |
| 排期表 | `docs/排期表_A_agentloom.xlsx`（11 阶段 / 41 任务 / 7 里程碑 / 220h） |

## 项目定位

「可恢复的 Agent 执行内核」——回答一个问题：这个 Agent 能不能安全跑完一件多步任务，中途挂了能不能接着跑，副作用会不会重复。

架构形态：**单一后端（不拆）**。README 开头必须主动写「为什么不用微服务」的判断依据，否则会被当成不懂微服务。

## 关键约定与决策

- **事件溯源是主干**：run / step / tool_call / tool_result / approval / error 六类事件；`replay` 必须是纯函数（不依赖当前时间、随机数、字典序）。
- **幂等是立身之本**：幂等键 = `hash(run_id + step_seq + tool_name + normalized_args)`，参数必须归一化（排序、去空白）。seq 递增靠唯一索引冲突重试，**不用** `SELECT MAX + 1`。
- **不建 BaseTool 抽象基类**，工具注册表只要 dict。
- **上下文裁剪固定保留**：首个 user 意图 + 最近 3 轮 + 工具原始结果摘要。
- **SSE 用 fetch-event-source**，不用原生 EventSource（带不了 JWT，该决策要写进 README）。
- **前端不能撒谎**：审批后重拉快照，不在前端本地改状态。
- `trace.jsonl` 是三项目串联的唯一硬接口，字段必须与 A03 定义一致。

## 环境事实（本机）

- Python：`D:\dsh-data\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（3.12.14）
- Node v24.16.0；pnpm 在 `D:\node_global\pnpm.cmd`
- **本机没有 GNU make**（PATH / Git / Chocolatey / Winget 均无）→ 采用 `Makefile` + `make.ps1` + `make.cmd` 三件套
- **只有 Windows PowerShell 5.1**（`C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe`），**没有 pwsh 7**
- PowerShell 执行策略全 Undefined → 跑本地脚本要 `-ExecutionPolicy Bypass`
- PowerShell 5.1 **无 BOM 时按 ANSI 代码页解析脚本**，中文会解成乱码引发语法错误 → `make.ps1` 必须存成 UTF-8 **with BOM**（`.gitattributes` 里已标 `make.ps1 -text` 防止转换）
- `npm.ps1` 被执行策略禁用 → 走 `npm.cmd`
- 非管理员，不能用 Chocolatey 装系统级工具

## 常用命令

```sh
# Linux / CI / Docker 内
make lint && make test

# Windows（本机，在仓库根目录）
make lint          :: make.cmd 转发到 make.ps1，目标名与 Makefile 一致
make test
make check         :: lint + typecheck + test
# 或直接：
powershell -NoProfile -ExecutionPolicy Bypass -File make.ps1 check
```

## 踩坑记录

- **`uvicorn app.main:app` 需要模块级 `app`**：只暴露 `create_app()` 工厂时，单测全绿但服务起不来
  （`Attribute "app" not found in module "app.main"`）。已在 `app/main.py` 末尾加 `app = create_app()`，
  并补了回归测试 `test_module_level_asgi_app_exists`。
- **starlette 1.10 的 TestClient 首选 `httpx2`**，缺失时回落 `httpx` 并发 `StarletteDeprecationWarning`；
  项目 `filterwarnings = ["error"]` 会把它变成错误。`httpx2>=2.16,<3.0` 已加入 dev 依赖。

## 待办 / 开放问题

- A02 要写 docker compose（postgres16 + 应用），届时需要 Docker Desktop 运行 WSL2。
- 模型 API Key（DeepSeek 或 OpenAI）尚未配置，A10 前需要。

## 按天记录索引

- [2026-11-23](2026-11-23.md) — 项目启动，完成 A01 工程骨架
