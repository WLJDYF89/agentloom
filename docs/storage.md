# 存储：events 表与迁移

> 这份文档说明事件落到 PostgreSQL 里的形状，以及为什么是这么形状。
> 事件本身的字段定义在 [events.md](events.md)，这里只讲存储。

## 一、表结构

```sql
CREATE TABLE events (
    event_id        text        NOT NULL,
    run_id          text        NOT NULL,
    seq             integer     NOT NULL,
    type            text        NOT NULL,
    trace_id        text        NOT NULL,
    schema_version  smallint    NOT NULL,
    actor           text        NOT NULL,
    created_at      timestamptz NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    payload         jsonb       NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT pk_events PRIMARY KEY (event_id),
    CONSTRAINT ck_events_seq_positive CHECK (seq >= 1),
    CONSTRAINT ck_events_schema_version_positive CHECK (schema_version >= 1),
    CONSTRAINT uq_events_run_seq UNIQUE (run_id, seq)
);
```

DDL 的唯一真相来源是 [`backend/app/db/ddl.py`](../backend/app/db/ddl.py) 里的 `EVENTS_DDL`。
迁移脚本从它取语句、测试也从它取，这样「迁移建的表」和「测试期望的表」不会手抄漂移。

### 为什么信封拆成列、载荷塞进 jsonb

信封字段（上表前 8 个，即 `ENVELOPE_FIELDS`）是所有 13 个事件类型共有的，且全部要参与
查询或约束：

| 字段 | 拆列的理由 |
| --- | --- |
| `run_id` + `seq` | `UNIQUE (run_id, seq)` 必须建在真实列上。jsonb 里的唯一约束只能靠表达式索引，报错信息也更难读 |
| `type` | 按类型过滤是审计与调试的常规操作（`WHERE type = 'tool.failed'`） |
| `trace_id` | 排查时从一次请求反查它触发的所有事件 |
| `created_at` | 时间范围查询、按时间排序 |
| `schema_version` | 演进时要能按版本分桶统计 |
| `actor` | 「谁触发的」是审批与审计的核心字段 |

其余字段每种事件各不相同（`run.started` 有 `task` 和 `model`，`tool.failed` 有 `error`，
`approval.granted` 有 `decided_by`……），拆成列会让表有两百个稀疏列。
它们整体进 `payload jsonb`，用 GIN 索引支持 `@>` 查询。

这也是事件溯源系统的常规做法：**能约束、能过滤的进列，语义丰富的进文档**。

### 两条时间戳为什么要分开

- `created_at`：事件**发生**的时间，由业务代码写入，参与 schema、参与 hash。
- `recorded_at`：事件**落库**的时间，由数据库 `DEFAULT now()` 填，不在 schema 里。

分开是因为 A07 要求「同一事件流重放 100 次，状态 hash 完全一致」。如果 hash 里混进
「落库时间」，同一份数据每次重放都会算出不同 hash。`recorded_at` 只用来排查
「业务时间和入库时间差多少」，永远不进 hash。

### `uq_events_run_seq` 是 A06 的地基

这条约束不是顺手加的，A06 的整个并发方案都建立在它上面：

```
INSERT INTO events (...) VALUES (...)
ON CONFLICT (run_id, seq) DO NOTHING RETURNING event_id
```

一次数据库往返就是原子操作，冲突时返回空行、外层重算 seq 再试。
如果没有这条唯一约束做兜底，两个并发写入者会拿到同一个 seq，事件流就断了——

而**事件流一旦断，replay 就不可能重建出确定的状态**，A07 的「重放 100 次 hash 一致」
会变成概率性通过。所以这条约束的存在意义是「让错误尽早以异常形式暴露」，
而不是「防止数据重复」这么简单。

## 二、四条索引

| 索引 | 支持的查询 |
| --- | --- |
| `ix_events_run_type (run_id, type, seq)` | 单个 run 的全量读（A07 重放的主查询）；按类型过滤某个 run 的事件 |
| `ix_events_trace (trace_id)` | 从一次 HTTP 请求反查它触发的全部事件 |
| `ix_events_created_at (created_at)` | 时间范围检索、清理策略 |
| `ix_events_payload_gin USING gin (payload jsonb_path_ops)` | `payload @> '{"decision":"deny"}'` 这类按载荷内容过滤的审计查询 |

`ix_events_run_type` 把 `seq` 放在第三位，这样「取某个 run 的全部事件并按 seq 排序」
可以只靠索引扫描完成，不需要额外排序。

`jsonb_path_ops` 比默认的 `jsonb_ops` 索引小很多也快很多，代价是只支持 `@>` 和 `?`
两种操作符，不支持 `->` 取键值。这个项目里载荷查询都是「某个字段等于某个值」，
用 `@>` 表达，所以选 `jsonb_path_ops`。

> 空表时 Postgres 规划器一定选顺序扫描，`EXPLAIN` 看不到索引名字。
> `tests/test_db_schema.py` 里验证这条索引的用例会先 `SET LOCAL enable_seqscan = off`
> 再取计划——验证的是「索引可用」，不是「规划器此刻会选它」。

## 三、为什么不用 ORM

决策：**Alembic 管迁移版本，DDL 手写（`op.execute`），查询侧 asyncpg 裸 SQL，不建 ORM 模型。**

ORM 的价值有三块：类型安全的查询、少写样板、复杂对象图的关系加载。
这个项目三块都不成立：

1. **没有复杂对象图。** 一共四张表（events / tool_executions / approvals / snapshots），
   表之间靠 `run_id` 弱关联，没有外键级联、没有 eager loading 的需求。
2. **`events` 是 append-only。** 对它只有两种操作：插入，和「按 `run_id` 顺序全量读」。
   没有 UPDATE、没有 DELETE、没有复杂 join。为两种操作上 ORM，收益不如它带来的抽象成本。
3. **并发控制靠 SQL 语义，不靠对象状态。** `ON CONFLICT ... RETURNING` 是数据库层的原子操作；
   ORM 的做法是 `session.add()` → 撞 `IntegrityError` → 回滚 → 重试，
   把正常控制流交给异常处理，在并发下容易写出「回滚后 session 已污染」的隐蔽 bug。

代价也要说清楚：查询结果没有类型检查（asyncpg 返回 `Record`，字段名拼错要到运行时
才炸）。这个代价目前可以接受，因为走数据库的只有 A06（写事件）、A07（读事件）、
A08（快照）三处，且都有连库测试覆盖。

## 四、迁移怎么用

```powershell
make migrate           # 迁移到最新版本
make migrate-down      # 回退一个版本
make migrate-history   # 看历史与当前版本
```

等价的手动命令（在 `backend/` 下）：

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

连接串从 `get_settings().database_url` 读，**不写在 `alembic.ini` 里**，
这样密码不进版本库。要指向别的库，改环境变量 `AGENTLOOM_DATABASE_URL` 即可。

### 与 `deploy/postgres/init/` 的分工

`deploy/postgres/init/*.sql` 只在**数据卷为空的第一次启动**跑一次，由 postgres 官方镜像
的 entrypoint 执行。它不是迁移机制。

所以**建表一律走迁移**。如果往 `init/` 里加 `02-events.sql`，现在能靠 `down -v` 生效，
但等 A09 有测试数据、A26 有真实运行记录之后，这条路等于每次加表都毁掉全部数据。

`init/01-init.sql` 现在只做一件事：容器首次起来时打一行 `RAISE NOTICE`，
确认库能连、版本与库名符合预期。它不建任何业务表。

## 五、加新表的流程

以 A19 的幂等去重表为例：

1. 在 `app/db/ddl.py` 里加 `TOOL_EXECUTIONS_DDL`（元组，每条语句一个元素——
   asyncpg 的 prepared statement 不接受多语句拼接）。
2. `python -m alembic revision -m "幂等执行记录"` 生成空版本文件，
   把 `revision` 编号接着往下排（`0002`），`down_revision` 填上一个版本号。
3. `upgrade()` 里 `for statement in TOOL_EXECUTIONS_DDL: op.execute(statement)`，
   `downgrade()` 反向 DROP。
4. `make migrate` 验证能上能下。
5. 在 `tests/` 里验证表结构与关键约束（唯一约束、CHECK、索引可用性）。

不写 `autogenerate`：它扫不出部分唯一索引的 `WHERE` 子句（A19 的
`CREATE UNIQUE INDEX ... WHERE status = 'running'` 就是这种），
下次迁移会误以为索引不存在而删掉重建，静默丢约束。
