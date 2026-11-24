# agentloom —— 可恢复的 Agent 执行内核
#
# 所有目标都只调用 backend/.venv 里的解释器，不依赖全局 Python。
# Windows 没有 GNU make 时，用等价入口：make <目标>（make.cmd 转发到 make.ps1）

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND      := backend
VENV         := $(BACKEND)/.venv
PY           := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip

COMPOSE      := docker compose -f deploy/docker-compose.yml

.PHONY: help setup venv deps lint format typecheck test test-cov check run clean \
        up down logs ps up-build migrate migrate-down migrate-history

help: ## 显示可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: venv deps ## 一键初始化（建 venv + 装依赖）
	@echo "✓ 环境就绪"

venv: ## 创建虚拟环境
	@test -d $(VENV) || python3.12 -m venv $(VENV)

deps: venv ## 安装依赖（含 dev）
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -e "$(BACKEND)[dev]"

lint: ## ruff 检查（不修改文件）
	@$(PY) -m ruff check $(BACKEND)
	@$(PY) -m ruff format --check $(BACKEND)

format: ## ruff 自动修复 + 格式化
	@$(PY) -m ruff check --fix $(BACKEND)
	@$(PY) -m ruff format $(BACKEND)

typecheck: ## mypy 严格模式
	@cd $(BACKEND) && .venv/bin/python -m mypy

test: ## 跑测试
	@cd $(BACKEND) && .venv/bin/python -m pytest

test-cov: ## 跑测试 + 覆盖率报告
	@cd $(BACKEND) && .venv/bin/python -m pytest --cov=app --cov-report=term-missing

check: lint typecheck test ## 提交前全量检查

run: ## 本地启动开发服务器
	@cd $(BACKEND) && .venv/bin/python -m app

# ---- Docker Compose 全栈 ----
# 注意：这些目标故意不进 check 的依赖链 —— CI 环境通常没有 Docker 守护进程，
# 放进去会让 `make check` 无辜失败。

up: ## 起全栈（postgres + backend）并等到健康
	@$(COMPOSE) up -d --wait
	@echo "✓ 全栈就绪：http://localhost:$${BACKEND_PORT:-8000}/health"

up-build: ## 重新构建镜像后再起（改过 Dockerfile 或依赖时用）
	@$(COMPOSE) up -d --build --wait
	@echo "✓ 全栈就绪（已重建镜像）"

down: ## 停容器（保留数据卷）
	@$(COMPOSE) down

logs: ## 跟随全栈日志
	@$(COMPOSE) logs -f

ps: ## 查看容器与健康状态
	@$(COMPOSE) ps

# ---- 数据库迁移 ----
# 迁移才是正规路径：deploy/postgres/init/ 下的 SQL 只在空数据卷的第一次启动跑一次。

migrate: ## 迁移到最新版本
	@cd $(BACKEND) && .venv/bin/python -m alembic upgrade head

migrate-down: ## 回退一个版本
	@cd $(BACKEND) && .venv/bin/python -m alembic downgrade -1

migrate-history: ## 查看迁移历史与当前版本
	@cd $(BACKEND) && .venv/bin/python -m alembic history --verbose
	@cd $(BACKEND) && .venv/bin/python -m alembic current

clean: ## 清理缓存产物
	@rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	@find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
