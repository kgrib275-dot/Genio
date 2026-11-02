#!/usr/bin/env bash
# lint / type / test 를 순서대로 실행한다.
# 인자 없이 실행하면 전부, lint|type|test 중 하나를 주면 그 단계만 실행한다.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -d .venv/Scripts ]]; then VENV_BIN=.venv/Scripts; else VENV_BIN=.venv/bin; fi
if [[ ! -d "$VENV_BIN" ]]; then
  echo "[check] 파이썬 가상환경(.venv)이 없습니다." >&2
  echo "[check] 'make setup' 또는 'python -m venv .venv' 후 requirements 설치를 먼저 실행하세요." >&2
  exit 1
fi
if [[ ! -d apps/web/node_modules ]]; then
  echo "[check] 웹 의존성(apps/web/node_modules)이 없습니다." >&2
  echo "[check] 'make setup-web' 또는 'cd apps/web && npm install' 을 먼저 실행하세요." >&2
  exit 1
fi

step="${1:-all}"

run_lint() {
  echo "== [lint] ruff =="
  "$VENV_BIN/ruff" check apps packages
  "$VENV_BIN/ruff" format --check apps packages
  echo "== [lint] eslint + prettier =="
  (cd apps/web && npm run --silent lint && npm run --silent format:check)
}

run_type() {
  echo "== [type] mypy --strict =="
  "$VENV_BIN/mypy"
  echo "== [type] tsc =="
  (cd apps/web && npm run --silent typecheck)
}

run_test() {
  echo "== [test] pytest =="
  "$VENV_BIN/python" -m pytest -q
  echo "== [test] vitest =="
  (cd apps/web && npm run --silent test)
}

case "$step" in
  lint) run_lint ;;
  type) run_type ;;
  test) run_test ;;
  all)
    run_lint
    run_type
    run_test
    echo
    echo "[check] lint + type + test 모두 통과"
    ;;
  *)
    echo "사용법: scripts/check.sh [lint|type|test]" >&2
    exit 2
    ;;
esac
