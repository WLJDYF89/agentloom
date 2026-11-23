# 事件模型

六族事件的定义。`backend/app/events/schema.py` 是本文档的实现，两者不一致时以本文档为准再改代码。

## 1. 设计原则

1. **信封与载荷分离**。所有事件共有的字段放信封，各族特有的放 payload。对应 A05 的表结构：信封字段单独成列（便于索引与 seq 唯一约束），其余整体进 `payload jsonb`。
2. **事件不可变**。写入即历史，模型 `frozen=True`，且 `extra="forbid"`（多一个字段就报错，避免静默丢数据）。
3. **时间戳一律 UTC aware**。用 `AwareDatetime`，naive datetime 直接拒绝。A07 重放时区一歪 hash 就对不上。
4. **`seq` 与 `step_seq` 不是一个东西**。`seq` 是单 run 内的全局事件序号（A06 靠唯一索引保证严格递增），`step_seq` 是"第几步"。同一步会产生多条事件，它们的 `seq` 不同、`step_seq` 相同。
5. **replay 只读事件，不读时钟**。重放代码里不允许出现 `now()` / `uuid4()` / 随机数。事件里的时间是"当时写入的"，不是"读出来算的"。

## 2. 信封

每个事件都有：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | `int` | 固定 `1`。改字段语义时才 +1，见第 6 节 |
| `event_id` | `str` | `uuid4().hex`，32 位。只做唯一标识，排序一律看 `seq` |
| `run_id` | `str` | 所属 run |
| `seq` | `int` | 单 run 内从 1 开始严格递增，不允许空洞 |
| `type` | `Literal[...]` | 具体事件类型，同时充当判别式（discriminator） |
| `trace_id` | `str` | 贯穿 run → step → tool_call，与 HTTP 头 `X-Trace-Id` 同一套值 |
| `created_at` | `AwareDatetime` | 写入时间，UTC |
| `actor` | `Actor` | `system` / `agent` / `human` / `tool`，谁产生的这条事件 |

`actor` 回答"这类事件是谁发的"，具体是谁（哪个审批人）放在 payload 里。

## 3. 六族事件

族由 `type` 的前缀区分。**族是分组概念，不是模型数量**——共 13 个具体类型：run 3、step 3、tool 3、approval 3、error 1。

### 3.1 run —— run 的生命周期

| type | 何时写 |
| --- | --- |
| `run.started` | 收到任务、创建 run 时。整条流的起点 |
| `run.resumed` | 崩溃后恢复、或审批通过后继续。A21/A25 用 |
| `run.finished` | 终态。run 结束后不再有新事件 |

`run.started` payload：
- `task: str` —— 用户原始任务原文。A12 裁剪时规定必须保留"首个 user 意图"，就是它。
- `model: str` —— 使用的模型
- `max_steps: int = 20`
- `token_budget: int | None`
- `cost_budget_usd: float | None`

`run.resumed` payload：
- `reason: "restart" | "approval_granted"`
- `from_seq: int` —— 从哪条事件之后继续重放

`run.finished` payload：
- `status: RunStatus` —— 见下表
- `reason: str | None`
- `steps_used: int`
- `tokens_used: int`
- `cost_usd: float`

`RunStatus`：`succeeded` / `failed` / `cancelled` / `stopped_max_steps` / `stopped_budget` / `stopped_consecutive_failures`。
终止条件是 A11 的四种（finish 工具、max_steps、token 预算、连续失败 N 次），这里一一对应。

### 3.2 step —— 单步循环

| type | 何时写 |
| --- | --- |
| `step.started` | 进入第 n 步 |
| `step.llm_response` | 模型返回。含内容、计划调用、token、耗时、成本 |
| `step.finished` | 该步收口 |

`step.started` payload：
- `step_seq: int` —— 第几步，从 1 开始
- `attempt: int = 1` —— 同一步的重试次数（A13 校验失败回灌重试，≤3）

`step.llm_response` payload：
- `model: str`
- `content: str` —— 模型的自然语言输出
- `tool_calls: list[PlannedToolCall]` —— **计划**要调的，不代表真的调了
- `finish_reason: str`
- `tokens_prompt: int` / `tokens_completion: int`
- `latency_ms: int`
- `cost_usd: float`

`PlannedToolCall`：`call_id: str` / `tool_name: str` / `args: dict[str, Any]`

`step.finished` payload：
- `outcome: "continue" | "finish" | "failed"`

**为什么 `llm_response` 单独一条而不塞进 `step.finished`**：它带 token 与成本，A10 记账要用；A07 replay 要按它重建"上一轮模型说了什么"喂回下一轮；A12 裁剪要按它统计轮次。塞进 finished 会让这些都得先拆。

### 3.3 tool_call —— 工具调用请求

只有一个 type：`tool.requested`。

排期表 A14 里叫 `tool_called`，这里改名，理由：**被策略拒绝的调用根本没"call"，但必须留痕**（A22 要求"越权调用 100% 拦截且有审计记录"）。用 `requested` 覆盖"请求了、批了、拒了"三种情况。

payload：
- `step_seq: int`
- `call_id: str` —— 与 `PlannedToolCall.call_id` 对应
- `tool_name: str`
- `args: dict[str, Any]` —— 模型给的原始参数，不改
- `normalized_args: dict[str, Any]` —— 归一化后（排序、去空白），A19 幂等键的输入
- `idempotency_key: str` —— `hash(run_id + step_seq + tool_name + normalized_args)`
- `timeout_ms: int`
- `decision: "allow" | "needs_approval" | "deny"`

`decision` 落在事件里而不是只在内存里判断，是为了**审计**：事后能回答"这次调用当时被判成什么"。
`deny` 时不会再有对应的 `tool.completed` / `tool.failed`，replay 靠这个判定"被拦截"。

### 3.4 tool_result —— 执行结果

| type | 何时写 |
| --- | --- |
| `tool.completed` | 执行成功 |
| `tool.failed` | 执行失败（超时、异常、业务错误） |

两个 type 而不是一个带 `ok` 布尔，因为 discriminated union 下"成功必有 result、失败必有 error"由类型保证，不用在代码里判空。

`tool.completed` payload：
- `step_seq: int` / `call_id: str`
- `result: Any` —— 工具返回值，已截断
- `truncated: bool` —— 是否因超长被截断（A17 返回值截断）
- `duration_ms: int`

`tool.failed` payload：
- `step_seq: int` / `call_id: str`
- `error: ToolError`
- `duration_ms: int`

`ToolError`：`kind: str` / `message: str` / `retriable: bool`

### 3.5 approval —— 人工闸门

| type | 何时写 |
| --- | --- |
| `approval.requested` | 工具 `needs_approval`，run 挂起 |
| `approval.granted` | 批准或改参后放行 |
| `approval.rejected` | 驳回，该调用终止 |

`approval.requested` payload：`step_seq` / `call_id` / `tool_name` / `args` / `risk: str`（为什么需要审批，给人看的话）

`approval.granted` payload：`step_seq` / `call_id` / `approver: str` / `args_override: dict | None` / `note: str | None`

`approval.rejected` payload：`step_seq` / `call_id` / `approver: str` / `reason: str`

A24 要求"审批事件（谁、何时、批了什么）"—— 谁在 `approver`，何时在信封 `created_at`，批了什么在 `args_override`。
`args_override` 非空时，**实际执行的参数是它**，`tool.requested` 里的 `args` 保持不变（历史不可改）。

### 3.6 error —— 错误

只有一个 type：`error.raised`。

payload：`kind: ErrorKind` / `message: str` / `retriable: bool` / `step_seq: int | None` / `call_id: str | None` / `context: dict | None`

`ErrorKind`：`llm_error` / `tool_timeout` / `schema_validation` / `policy_denied` / `internal`

A16 的"10 类错误参数有可读提示"落在 `schema_validation` 下，具体哪个参数错放 `context`。

## 4. 示例 JSON

### run.started

```json
{
  "schema_version": 1,
  "event_id": "3f2a9c1e4b8d4f7a9c2e5d1b6a8f3c7e",
  "run_id": "run_01HQZ9X2",
  "seq": 1,
  "type": "run.started",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:15:33.412000Z",
  "actor": "human",
  "task": "查一下工单 #1234 的进展，如果是超时状态就发邮件通知负责人",
  "model": "deepseek-chat",
  "max_steps": 20,
  "token_budget": null,
  "cost_budget_usd": null
}
```

### step.llm_response

```json
{
  "schema_version": 1,
  "event_id": "8d1b4c7e2a9f4d3b8e5c1a7f2d4b9e6c",
  "run_id": "run_01HQZ9X2",
  "seq": 4,
  "type": "step.llm_response",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:15:35.882000Z",
  "actor": "agent",
  "step_seq": 2,
  "model": "deepseek-chat",
  "content": "先查工单状态。",
  "tool_calls": [
    {"call_id": "call_1", "tool_name": "get_ticket", "args": {"ticket_id": "1234"}}
  ],
  "finish_reason": "tool_calls",
  "tokens_prompt": 412,
  "tokens_completion": 38,
  "latency_ms": 1180,
  "cost_usd": 0.000214
}
```

### tool.requested

```json
{
  "schema_version": 1,
  "event_id": "a1c3e5f72b8d4e6a9c0b2d4f6a8e1c3",
  "run_id": "run_01HQZ9X2",
  "seq": 5,
  "type": "tool.requested",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:15:35.901000Z",
  "actor": "agent",
  "step_seq": 2,
  "call_id": "call_1",
  "tool_name": "get_ticket",
  "args": {"ticket_id": "1234"},
  "normalized_args": {"ticket_id": "1234"},
  "idempotency_key": "9c1f2a7e5b3d8c4a6e0f2b1d9a8c7e5",
  "timeout_ms": 5000,
  "decision": "allow"
}
```

### tool.completed

```json
{
  "schema_version": 1,
  "event_id": "b2d4f6a8c0e2f4a6b8d0c2e4f6a8b0d2",
  "run_id": "run_01HQZ9X2",
  "seq": 6,
  "type": "tool.completed",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:15:36.043000Z",
  "actor": "tool",
  "step_seq": 2,
  "call_id": "call_1",
  "result": {"ticket_id": "1234", "status": "open", "updated_at": "2026-11-23T10:02:00Z"},
  "truncated": false,
  "duration_ms": 42
}
```

### approval.granted

```json
{
  "schema_version": 1,
  "event_id": "c3e5a7c9d1f3b5d7e9a1c3e5b7d9f1a3",
  "run_id": "run_01HQZ9X2",
  "seq": 11,
  "type": "approval.granted",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:18:07.220000Z",
  "actor": "human",
  "step_seq": 4,
  "call_id": "call_3",
  "approver": "qianz",
  "args_override": {"to": "ops@corp.example", "subject": "工单 1234 超时"},
  "note": "收件人改成运维组"
}
```

### error.raised

```json
{
  "schema_version": 1,
  "event_id": "d4f6b8d0e2a4c6e8f0b2d4f6a8c0e2b4",
  "run_id": "run_01HQZ9X2",
  "seq": 9,
  "type": "error.raised",
  "trace_id": "5888caede20946f4a54ce913d7401552",
  "created_at": "2026-11-24T02:16:02.104000Z",
  "actor": "system",
  "kind": "schema_validation",
  "message": "参数 ticket_id 应为字符串，收到 1234",
  "retriable": true,
  "step_seq": 3,
  "call_id": "call_2",
  "context": {"field": "ticket_id", "expected": "string", "got": "integer"}
}
```

## 5. 序列化与 hash 规范化

A07 要"同一事件流重放 100 次状态 hash 完全一致"，前提是**同一份数据序列化出同一串字节**。

规则：

1. JSON `sort_keys=True`，分隔符 `(",", ":")` 紧凑格式，不缩进。
2. datetime 一律转 UTC 再以 ISO 8601 输出，毫秒精度，`Z` 结尾（不是 `+00:00`）。
3. 浮点数按原样输出，不做舍入——但**可比量不要用浮点存**（成本已在上游按 `Decimal` 算好后转 str 或按分存整数，避免 0.1+0.2 这类差异）。
4. `None` 保留为 `null`，不删字段。

`schema.canonical_json(event)` 实现了 1–4，A07 直接用。

## 6. 演进规则

- **只加不删不改**。新字段必须有默认值，老事件反序列化不受影响。
- 改字段语义（同一个名字换了含义）才升 `schema_version`，且 replay 要按版本分支处理。
- 新增事件类型不需要升版本，老代码遇到不认识的 `type` 应当忽略而不是崩溃。

## 7. 与后续任务的关系

| 任务 | 依赖本模型的哪里 |
| --- | --- |
| A05 建表 | 信封字段成列，其余进 `payload jsonb`；`(run_id, seq)` 唯一约束 |
| A06 追加 | `seq` 严格递增，靠唯一索引冲突重试 |
| A07 replay | `canonical_json` + 纯函数重建 RunState，不读时钟 |
| A08 快照 | 每 N 条落物化状态，重放从最近快照起 |
| A14 每步落事件 | 直接对应 `step.*` 与 `tool.*` |
| A19 幂等键 | `tool.requested.idempotency_key` 的计算口径 |
| A21 三态判定 | "有 `tool.requested` 但没有 `tool.completed`/`tool.failed`" = 执行中 |
| A22 越权审计 | `decision == "deny"` 的事件 + `error.raised(policy_denied)` |
| A30 埋点 | `trace_id` 贯穿，span 层级 = run → step → tool_call |
