#!/usr/bin/env bash
# DB 자동 백업(docker-compose의 backup 서비스가 실행). 매일 GENIO_BACKUP_HOUR시에 pg_dump(-Fc)로
# /backups/genio-YYYYmmdd-HHMM.dump 를 만들고, GENIO_BACKUP_KEEP_DAYS일보다 오래된 파일은 지운다.
# 결과는 /backups/status.json 에 남겨 관리 > 시스템 상태 화면이 읽는다.
# 처음 켰을 때 최근 하루 안에 만든 백업이 없으면 바로 한 번 만든다.
set -u

DIR=/backups
HOUR="${GENIO_BACKUP_HOUR:-3}"
KEEP="${GENIO_BACKUP_KEEP_DAYS:-7}"
export PGPASSWORD="${POSTGRES_PASSWORD:-genio}"
PGUSER="${POSTGRES_USER:-genio}"
PGDB="${POSTGRES_DB:-genio}"
PGHOST="${PGHOST:-postgres}"
mkdir -p "$DIR"

write_status() { # status file size_mb message last_success
  local tmp="$DIR/.status.json.tmp"
  printf '{"status":"%s","file":"%s","size_mb":%s,"message":"%s","last_success":"%s","last_attempt":"%s","keep_days":%s}\n' \
    "$1" "$2" "$3" "$4" "$5" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$KEEP" > "$tmp" && mv "$tmp" "$DIR/status.json"
}

last_success() {
  if [ -f "$DIR/status.json" ]; then
    sed -n 's/.*"last_success":"\([^"]*\)".*/\1/p' "$DIR/status.json"
  fi
}

run_backup() {
  local name="genio-$(date +%Y%m%d-%H%M).dump"
  local out="$DIR/$name"
  echo "[backup] $(date) 시작: $name"
  if pg_dump -h "$PGHOST" -U "$PGUSER" -d "$PGDB" -Fc -f "$out.part" 2> "$DIR/.last_error.log"; then
    mv "$out.part" "$out"
    local mb
    mb=$(awk -v b="$(stat -c %s "$out")" 'BEGIN { printf "%.1f", b/1048576 }')
    write_status ok "$name" "$mb" "" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[backup] 완료: $name (${mb}MB)"
    find "$DIR" -maxdepth 1 -name 'genio-*.dump' -mtime +"$KEEP" -print -delete
  else
    rm -f "$out.part"
    local msg
    msg=$(head -c 200 "$DIR/.last_error.log" | tr '"\\\n\r' "'/  ")
    write_status error "" 0 "pg_dump 실패: $msg" "$(last_success)"
    echo "[backup] 실패: $msg" >&2
  fi
}

# 시작할 때: 최근 24시간 안의 백업 파일이 없으면 바로 한 번
if [ -z "$(find "$DIR" -maxdepth 1 -name 'genio-*.dump' -mmin -1440 2>/dev/null | head -1)" ]; then
  run_backup
fi

done_day=""
while true; do
  now_hour=$(date +%-H)
  today=$(date +%Y%m%d)
  if [ "$now_hour" = "$HOUR" ] && [ "$done_day" != "$today" ]; then
    run_backup
    done_day="$today"
  fi
  sleep 60
done
