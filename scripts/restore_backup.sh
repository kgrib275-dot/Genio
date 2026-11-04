#!/usr/bin/env bash
# 백업 파일로 DB를 되돌린다. 지금 DB 내용은 백업 시점으로 바뀐다(되돌릴 수 없음).
# 사용: bash scripts/restore_backup.sh backups/genio-20261104-0300.dump
# 순서: api·worker를 멈춤 → 지금 DB를 안전 백업(before-restore-*.dump) → 복구 → api·worker 다시 시작
set -euo pipefail
cd "$(dirname "$0")/.."

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "[restore] 복구할 백업 파일을 찾지 못했어요." >&2
  echo "[restore] 예: bash scripts/restore_backup.sh backups/genio-20261104-0300.dump (목록: ls backups)" >&2
  exit 1
fi
NAME="$(basename "$FILE")"
PGUSER="${POSTGRES_USER:-genio}"
PGDB="${POSTGRES_DB:-genio}"

read -r -p "[restore] '$NAME'로 DB를 되돌릴까요? 지금 내용은 사라져요. (yes 입력) " ok
if [[ "$ok" != "yes" ]]; then
  echo "[restore] 취소했어요."
  exit 0
fi

echo "[restore] api·worker 멈춤"
docker compose stop api worker

SAFETY="before-restore-$(date +%Y%m%d-%H%M).dump"
echo "[restore] 지금 DB를 backups/$SAFETY 로 먼저 백업"
docker compose exec -T postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc > "backups/$SAFETY"

echo "[restore] $NAME 복구 중"
docker compose exec -T postgres pg_restore -U "$PGUSER" -d "$PGDB" --clean --if-exists --no-owner < "$FILE"

echo "[restore] api·worker 다시 시작"
docker compose start api worker
echo "[restore] 끝났어요. 문제가 있으면 backups/$SAFETY 로 같은 방법으로 되돌릴 수 있어요."
