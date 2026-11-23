# API 契约与错误约定

A04 的产物。写这份文档的目的不只是记录「有哪些接口」，更是记录**为什么这样分层**——
后面 B、C 两个项目要复用这套结构，接口一多就再也改不动了。

## 一、路由分层

```
/api/v1/...        业务接口（后续所有新接口都挂这里）
/health /version   运维接口（不带版本前缀）
/docs /openapi.json  OpenAPI（FastAPI 默认，不在 /api/v1 下）
```

运维接口**故意不带版本前缀**。原因是部署侧的健康检查、K8s 探针、监控这些配置是跨项目
复制的——一旦探针地址里带了 `v1`，将来出 `v2` 时所有部署配置都得跟着改，而探针本身
从来没有「版本」的概念。所以探针路径属于基础设施的一部分，稳定优先。

业务接口反过来，**必须带版本**。Agent 的接口形状在 P2 之后大概率要改（消息怎么组装、
审批怎么表达），带版本号意味着改动可以用 `/api/v2` 并行发布，旧客户端不会一夜失效。

分层落在目录上：

```
app/api/
├── deps.py      共享依赖 + 错误响应声明（ERROR_RESPONSES）
├── handlers.py  四个异常处理器
├── ops.py       运维接口
└── v1/          业务接口，__init__.py 里统一挂 /api/v1 前缀
```

`v1/__init__.py` 只做一件事：把子路由拼成一个挂了前缀的 `api_v1_router`。
这样将来加 `v2/` 时，`main.py` 完全不用动。

## 二、错误响应：只有一种形状

```json
{
  "code": "VALIDATION_FAILED",
  "message": "请求参数校验失败",
  "trace_id": "a104d7a2d63a455fbbcca07e0139aa45",
  "details": { "fields": [{ "loc": "body.task", "msg": "字段不能为空", "type": "missing" }] }
}
```

四个字段里只有前三个是必需的，`details` 为空时整个键不出现——不是 `null`。
理由：前端在 `details` 上做 `if (details?.fields)` 比 `if (details && details.fields)`
更容易写对。

### 为什么要有 `code`

`message` 是给人看的，会变（改文案、做多语言、补充上下文），**不能让代码依赖它**。
`code` 是稳定的机器可读标识，前端用它做分支判断，测试用它做断言。九个错误码：

| code | HTTP | 什么时候用 |
| --- | --- | --- |
| `BAD_REQUEST` | 400 | 请求本身不合语法 |
| `VALIDATION_FAILED` | 422 | 语法对但值不合法 |
| `UNAUTHORIZED` | 401 | 没认证 |
| `FORBIDDEN` | 403 | 认证了但没权限（A22 越权拦截用这个） |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 状态冲突，如 `seq` 撞了、run 已在别处推进 |
| `RATE_LIMITED` | 429 | 限流 |
| `INTERNAL_ERROR` | 500 | 兜底 |
| `DEPENDENCY_UNAVAILABLE` | 503 | 下游不可用（就绪探针用这个） |

### 四个异常处理器各管一摊

`handlers.py` 里注册四个，覆盖所有逃逸路径：

1. **`AppError`** → 按 `code` 映射 HTTP 状态。这是业务代码唯一该主动抛的东西。
2. **`RequestValidationError`** → 422。把 Pydantic 的 `errors()` 压平成 `{loc, msg, type}`，
   `loc` 用点号连成 `"body.task"`——原始结构是嵌套数组，前端处理起来要写递归。
   **注意**：不把 `input` 原样吐回去。请求体里可能有密钥，回显等于把它写进日志和前端控制台。
3. **`StarletteHTTPException`** → 把框架自己抛的（404 路由不存在、405 方法不对）也转成
   同一形状。不做这一步，`/nope` 会返回 `{"detail": "Not Found"}`，前端拿不到 `code`。
4. **`Exception`** → 500 兜底。**关键：栈只进日志，绝不进响应体。** 异常消息里经常带
   连接串、文件路径、内部主机名。测试里专门验证响应体不含 `Traceback`、不含异常消息原文。

### 为什么不允许裸 500

排期表的 A04 完成标准原文是「错误响应含 code / message / trace_id」，括号里补了一句
「不裸 500」。这两句说的是同一件事的两面：**用户看到的每个失败，都应该能对应到日志里的
一条记录**。没有 `trace_id` 的错误，用户报障时只能说「刚才报错了」，排查从随机猜测开始。

## 三、trace_id 怎么走完全程

```
客户端 ──X-Trace-Id（可选）──▶ 中间件 ──set_trace_id──▶ contextvar
                                    │
                                    ├─▶ 日志格式 %(trace_id)s
                                    ├─▶ 异常处理器 AppError.to_payload(trace_id)
                                    └─▶ 响应头 X-Trace-Id（回写）
```

用 `contextvars` 而不是把 trace_id 一路当参数传：A11 的 Agent 主循环会嵌套调用
LLM 客户端和工具执行器，每层都加一个 `trace_id` 参数会让签名很难看；`contextvars` 在
`async` 下天然跟着任务走。中间件在 `finally` 里 `reset_trace_id(token)`，防止请求间串味。

**校验规则**：不传就生成 32 位 hex（无连字符）。传了就用传的——但**不校验格式**，
这是有意的：调用方可能用它自己的请求 ID（`req-20261124-001` 这种），强制 32 位 hex
只会逼调用方再包一层。

## 四、为什么错误契约要写进 OpenAPI

`deps.py` 里有个 `ERROR_RESPONSES` 字典，每个接口都传 `responses=ERROR_RESPONSES`。
这不是装饰——它让 `/openapi.json` 里每个接口都带上 4xx/5xx 的响应形状，于是：

- 前端能直接从 OpenAPI 生成错误处理的类型，不用手抄；
- 后端加新接口时忘了声明会被测试抓到（`test_every_route_states_its_error_shape`
  逐个路由检查 `responses` 里有没有 `422`）。

这条测试看起来吹毛求疵，但它挡的是「新接口悄悄换了错误格式」——这类不一致不会让任何
测试变红，只会在联调时消耗半天。

## 五、A04 顺带做了的事

A04 只给 2 小时，是 P0 里最短的任务，所以除了分层和异常处理，只额外暴露了三个和事件
schema 相关的只读接口，用来验证「路由层能正确调用下层的校验逻辑」：

| 接口 | 作用 |
| --- | --- |
| `GET /api/v1/events/types` | 列出 13 个事件类型 + `schema_version` |
| `GET /api/v1/events/{type}/schema` | 取某类型的 JSON Schema，供前端/MCP 侧做表单 |
| `POST /api/v1/events/canonicalize` | 校验一条事件并返回规范化 JSON，A07 的 hash 复用同一函数 |

`canonicalize` 特别值得说：它把 A03 的 `canonical_json` **通过 HTTP 暴露出来了**。
A07 要验证「同一事件流重放 100 次，状态 hash 一致」，那时出问题时第一件事就是拿两条事件
比对规范化字节——有了这个接口，不用写脚本就能在浏览器里比对。

## 六、A05 要接的东西

- `/ready` 就绪探针（查数据库连通性），与 `/health` 分开：
  存活探针失败 → 重启进程；就绪探针失败 → 从负载均衡摘掉，**不重启**。
  混在一起的后果是数据库抖动时把好进程全部重启，故障放大。
- `DEPENDENCY_UNAVAILABLE` 错误码届时正式启用（现在只是定义了）。
- 分页参数规范（`limit` / `cursor`），run 列表要用。
