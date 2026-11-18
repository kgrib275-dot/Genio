#!/usr/bin/env bash
# 복구 연습(운영 준비 1차 A3): 가장 최근 백업을 임시 DB(genio_verify)에 실제로 복구해 보고, 표마다 행 수를 센 뒤
# 임시 DB를 지운다. 지금 쓰는 DB는 건드리지 않는다. 결과는 /backups/verify.json 에 남겨 관리 > 시스템 상태가 읽는다.
# backup 서비스가 매주 일요일 백업 뒤에 자동으로 돌린다. 직접 돌리기:
#   docker compose exec backup bash /scripts/verify_backup.sh
set -u

DIR=/backups
export PGPASSWORD="${POSTGRES_PASSWORD:-genio}"
PGUSER="${POSTGRES_USER:-genio}"
PGHOST="${PGHOST:-postgres}"
TMPDB="genio_verify"
OUT="$DIR/verify.json"

write() { # status file seconds tables rows_json message
  local tmp="$DIR/.verify.json.tmp"
  printf '{"status":"%s","file":"%s","checked_at":"%s","seconds":%s,"tables":%s,"rows":%s,"message":"%s"}\n' \
    "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" "$4" "$5" "$6" > "$tmp" && mv "$tmp" "$OUT"
}

FILE=$(ls -1t "$DIR"/genio-*.dump 2>/dev/null | head -1)
if [ -z "$FILE" ]; then
  write error "" 0 0 "{}" "복구해 볼 백업 파일이 없어요."
  echo "[verify] 백업 파일이 없어요." >&2
  exit 1
fi
NAME=$(basename "$FILE")
START=$(date +%s)
echo "[verify] $(date) $NAME 을(를) 임시 DB에 복구해 봐요"

psql -h "$PGHOST" -U "$PGUSER" -d postgres -qc "DROP DATABASE IF EXISTS $TMPDB" >/dev/null 2>&1
if ! psql -h "$PGHOST" -U "$PGUSER" -d postgres -qc "CREATE DATABASE $TMPDB" >/dev/null 2> "$DIR/.verify_error.log"; then
  write error "$NAME" 0 0 "{}" "임시 DB를 만들지 못했어요."
  exit 1
fi
if ! pg_restore -h "$PGHOST" -U "$PGUSER" -d "$TMPDB" --no-owner --exit-on-error "$FILE" 2> "$DIR/.verify_error.log"; then
  MSG=$(head -c 200 "$DIR/.verify_error.log" | tr '"\\n\r' "'/  ")
  psql -h "$PGHOST" -U "$PGUSER" -d postgres -qc "DROP DATABASE IF EXISTS $TMPDB" >/dev/null 2>&1
  write error "$NAME" $(( $(date +%s) - START )) 0 "{}" "복구 실패: $MSG"
  echo "[verify] 복구 실패: $MSG" >&2
  exit 1
fi

Q="SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
TABLES=$(psql -h "$PGHOST" -U "$PGUSER" -d "$TMPDB" -tAc "$Q" 2>/dev/null || echo 0)
ROWS="{"
SEP=""
for t in users workspaces apps workflow_versions runs messages knowledge_bases documents; do
  n=$(psql -h "$PGHOST" -U "$PGUSER" -d "$TMPDB" -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo -1)
  ROWS="$ROWS$SEP\"$t\":${n:--1}"
  SEP=","
done
ROWS="$ROWS}"
psql -h "$PGHOST" -U "$PGUSER" -d postgres -qc "DROP DATABASE IF EXISTS $TMPDB" >/dev/null 2>&1
SECS=$(( $(date +%s) - START ))

STATUS=ok
MSG=""
if [ "${TABLES:-0}" -lt 10 ]; then
  STATUS=error
  MSG="복구한 DB에 표가 너무 적어요(${TABLES}개)."
fi
write "$STATUS" "$NAME" "$SECS" "${TABLES:-0}" "$ROWS" "$MSG"
echo "[verify] $STATUS: 표 ${TABLES}개, ${SECS}초, $ROWS"
