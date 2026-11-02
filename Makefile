# Genio 개발용 Makefile.
# Windows에 make가 없으면 같은 검사를 `bash scripts/check.sh` 로 실행할 수 있다.
SHELL := bash
.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
else
  VENV_BIN := .venv/bin
endif
PY := $(VENV_BIN)/python

.PHONY: help setup setup-py setup-web check lint type test fmt gen-types up down logs

help: ## 사용 가능한 명령 목록
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup: setup-py setup-web ## 로컬 개발 환경 준비(가상환경 + npm install)

setup-py:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

setup-web:
	cd apps/web && npm install

check: ## lint + type + test (API, 워커, 노드, 웹 전부)
	bash scripts/check.sh

lint: ## ruff + eslint + prettier 검사
	bash scripts/check.sh lint

type: ## mypy(strict) + tsc
	bash scripts/check.sh type

test: ## pytest + vitest
	bash scripts/check.sh test

fmt: ## 코드 자동 정리(ruff, prettier)
	$(VENV_BIN)/ruff format apps packages
	$(VENV_BIN)/ruff check --fix apps packages
	cd apps/web && npx prettier --write .

up: ## docker-compose 전체 기동
	docker compose up --build -d

down: ## docker-compose 종료
	docker compose down

logs: ## docker-compose 로그
	docker compose logs -f --tail=100
