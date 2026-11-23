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

.PHONY: help setup venv deps lint format typecheck test test-cov check run clean docker-up docker-down

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

docker-up: ## 起 postgres + 应用（A02 提供）
	@docker compose -f deploy/docker-compose.yml up -d

docker-down: ## 停容器
	@docker compose -f deploy/docker-compose.yml down

clean: ## 清理缓存产物
	@rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	@find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
