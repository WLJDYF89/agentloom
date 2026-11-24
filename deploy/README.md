# deploy

部署相关的一切：Docker Compose 编排、PostgreSQL 初始化脚本、运维说明。
镜像定义不在这里 —— 它跟着代码走，位于 [`backend/Dockerfile`](../backend/Dockerfile)，
理由是让 `build.context` 与 Dockerfile 同处一个目录，避免「dockerfile 相对 context
还是相对 compose 文件」这类路径坑。

## 一条命令起全栈

```powershell
make up        # 起 postgres:16 + backend，等到两者都 healthy 才返回
make ps        # 看容器与健康状态
make logs      # 跟随日志
make down      # 停容器，保留数据卷
```

`make up` 内部是 `docker compose -f deploy/docker-compose.yml up -d --wait`。
**`--wait` 是这条验收标准的关键**：不加它，`up -d` 会立刻返回 0，哪怕容器两秒后就崩了；
加了它，命令返回 0 就等于所有 healthcheck 都通过了。这就是「一条 `make up` 能起全栈」
的真实含义——不是「下发了启动命令」，而是「确认健康」。

改了 Dockerfile 或依赖之后用 `make up-build`，它会带 `--build` 重建镜像。

**`make up` 不会重建镜像**，它只是在已有镜像上重启容器。改了 Python 代码却只跑 `make up`，
容器里跑的还是旧代码 —— 表现是新加的接口 404，而 `make check` 全绿、本地 `make run` 也正常。
A04 加 `/api/v1` 时就踩过这个：宿主机上路由对，容器里 404，发现是镜像没重建。

## 手动等价命令

不通过 make 时（例如排查问题想看原始输出）：

```powershell
docker compose -f deploy/docker-compose.yml up -d --wait
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f
docker compose -f deploy/docker-compose.yml down
```

单独构建镜像（验证 Dockerfile 本身，不牵扯 compose）：

```powershell
docker build -t agentloom-backend:dev backend
```

## 目录结构

```
deploy/
├── docker-compose.yml        postgres:16 + backend 编排
├── postgres/init/
│   └── 01-init.sql           初始化 SQL（仅首次启动执行）
└── README.md
```

表结构与迁移不在这里，在 `backend/migrations/`。

## 端口

| 服务 | 宿主机 | 容器内 | 说明 |
| --- | --- | --- | --- |
| backend | 8000 | 8000 | `curl http://localhost:8000/health` |
| postgres | 5432 | 5432 | 宿主机本地开发（`make run`）连它 |

被占用时在 `.env` 里改 `BACKEND_PORT` / `POSTGRES_PORT`（compose 会读取），
不要直接改 compose 文件，否则改动容易在提交时被漏掉。

## 配置与两个地址的区别

这里有**两份**数据库地址，不能共用一个值：

| 场景 | 地址 | 写在哪 |
| --- | --- | --- |
| 宿主机本地开发（`make run`） | `...@localhost:5432/agentloom` | `.env` 的 `AGENTLOOM_DATABASE_URL` |
| 容器内应用 | `...@postgres:5432/agentloom` | compose 的 `environment`，会覆盖前者 |

原因很简单：**容器里的 `localhost` 指容器自己**，不是宿主机。写错的表现是
`Connection refused` 或「数据库不存在」，而 `docker compose ps` 里 postgres 明明是 healthy。

## 初始化 SQL 的执行时机（最容易踩的坑）

`deploy/postgres/init/*.sql` 只在**数据卷为空的第一次启动**时被执行，由 postgres
官方镜像的 `docker-entrypoint.sh` 按文件名字典序跑一遍。之后无论你改什么，都不会重跑。

所以改了 `01-init.sql` 想让它生效，必须删卷：

```powershell
docker compose -f deploy/docker-compose.yml down -v
make up
```

`down -v` 会**删掉整个数据库数据**。

## 表结构只有一条正规路径：迁移

`init/` 里那几份 SQL 不是迁移机制，它只做「容器第一次起来时确认库能连、时区对」这件事。
**表结构的唯一真相来源是 Alembic 迁移**，在 `backend/migrations/versions/` 下，
DDL 本身写在 `backend/app/db/ddl.py`（迁移脚本和测试都从那里取，避免手抄漂移）。

```powershell
make migrate           # 迁移到最新
make migrate-down      # 回退一个版本
make migrate-history   # 看历史与当前版本
```

为什么不让 `init/` 承担建表：等 A09 之后有测试数据、A26 之后有真实运行记录，
每次加表都要 `down -v` 才能让新 SQL 生效，那等于**每次都毁掉全部数据**。
迁移就不一样，`upgrade head` 只跑没跑过的那几个版本，数据不动。

## 当前阶段说明（A05）

A02 时 backend 容器不连库；**A05 起真连了**：`app/main.py` 的 lifespan 里建 asyncpg
连接池（`app/db/pool.py`），`settings.db_pool_autostart` 为真时启动就连。
所以现在 backend 容器如果连不上 postgres，`/ready` 会返回 503。

`/health` 仍是**存活探针**，只证明进程活着，不查下游；查库的是 `/ready`。
两者不能合并：合并之后数据库抖一下，编排层就会把好进程重启掉。

## 健康检查

两处定义，各管一摊：

- **backend**：写在 `backend/Dockerfile` 的 `HEALTHCHECK` 指令里（镜像级）。
  不用 curl/wget —— `python:3.12-slim` 里没有这两个命令，只能用 Python 的 `urllib.request` 发请求。
- **postgres**：写在 `docker-compose.yml` 里，用 `pg_isready -U ... -d ...`。

刻意不把 backend 的 healthcheck 也搬到 compose 里写成第二份，避免两处定义漂移。

## 已知限制

- **只在首次启动执行 init SQL**，见上节；建表走迁移。
- **没有源码热重载**：镜像里 COPY 的是构建时的代码，改了 Python 代码要 `make up-build`
  才生效。绑定挂载 + `--reload` 留到开发体验真正成为瓶颈时再加。
- **迁移不会随容器启动自动跑**：容器起来只连库不建表，要手动（或 CI 里）先 `make migrate`。
- **镜像源写死在 Dockerfile 里**（清华源），可用 `--build-arg PIP_INDEX_URL=...` 覆盖。
- **数据卷不绑定宿主机路径**：Windows 下把目录绑到 `/var/lib/postgresql/data`
  会因权限与大小写不敏感导致 initdb 失败，这是经典坑，所以用命名卷。
