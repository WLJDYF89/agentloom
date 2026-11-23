-- 01-init.sql —— postgres 初始化脚本
--
-- 执行时机：容器**第一次**启动且数据目录为空时，由 postgres 官方镜像的
--   docker-entrypoint.sh 自动执行 /docker-entrypoint-initdb.d/ 下的 *.sql。
-- 重要：数据目录已有内容时这个目录会被整体跳过。改了本文件必须
--   docker compose -f deploy/docker-compose.yml down -v
-- 把卷删掉才会重新执行。否则你会以为脚本生效了，其实没跑。
--
-- 当前阶段（A02）：
--   数据库 agentloom 与用户 agentloom 已由镜像根据环境变量
--   POSTGRES_USER / POSTGRES_DB 自动创建，这里无需再建。
--   本文件暂时只做一次自检，确认连接与权限正常。
--
-- 后续脚本按编号顺序命名，会被按字典序依次执行：
--   02-events.sql       ← A05 events 表（run_id + seq 唯一约束）
--   03-idempotency.sql  ← A19 幂等键去重表
--   04-snapshots.sql    ← A08 快照表
-- 注意 A05/A08/A19 的表若与 Python 侧建表（SQLAlchemy/Alembic）重叠，
-- 二者只能留一处作为唯一真相来源，届时再定。

-- 自检：打印版本与当前库名，容器日志里能看到就算初始化跑过了。
DO $$
BEGIN
    RAISE NOTICE 'agentloom init: % / db=%', version(), current_database();
END
$$;
