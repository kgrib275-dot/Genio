"""외부 백업(운영 준비 1차 A3): 매일 만든 DB 백업(pg_dump)을 바깥 S3 호환 저장소에도 올린다.

- backup 서비스가 /backups 에 genio-YYYYmmdd-HHMM.dump 를 만든다(scripts/backup_loop.sh).
- 워커가 한 시간마다(scheduler) 아직 올리지 않은 최근 백업을 올리고, 보관 기간이 지난 바깥 백업은 지운다.
- 결과는 Redis(genio:backup:offsite)에 남겨 관리 > 시스템 상태 '외부 백업'이 읽는다.
GENIO_BACKUP_S3_BUCKET을 비우면 아무것도 하지 않는다.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from api.config import Settings, get_settings

log = logging.getLogger("genio.backup")
STATE_KEY = "genio:backup:offsite"
DUMP_RE = re.compile(r"^genio-\d{8}-\d{4}\.dump$")
# 이보다 오래된 로컬 백업은 올리지 않는다(처음 켤 때 7일치를 한꺼번에 올리지 않게)
UPLOAD_RECENT_DAYS = 2


def enabled(st: Settings | None = None) -> bool:
    return bool((st or get_settings()).genio_backup_s3_bucket)


def _client(st: Settings) -> Any:
    from api.services.storage import make_s3_client

    return make_s3_client(st.model_copy(update={"genio_s3_bucket": st.genio_backup_s3_bucket}))


def _prefix(st: Settings) -> str:
    p = st.genio_backup_s3_prefix.strip().lstrip("/")
    return p if not p or p.endswith("/") else p + "/"


def _exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:
        resp = getattr(exc, "response", None) or {}
        code = str((resp.get("Error") or {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _save_state(state: dict[str, Any]) -> None:
    from api.engine.events import _client as redis_client

    r = redis_client()
    if r is None:
        return
    try:
        r.set(STATE_KEY, json.dumps(state, ensure_ascii=False), ex=30 * 24 * 3600)
    except Exception:
        log.warning("외부 백업 상태를 기록하지 못했어요")


def load_state() -> dict[str, Any] | None:
    from api.engine.events import _client as redis_client

    r = redis_client()
    if r is None:
        return None
    try:
        raw = r.get(STATE_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def sync(now: datetime | None = None, client: Any = None) -> dict[str, Any]:
    """올릴 백업을 올리고 오래된 바깥 백업을 지운다. 결과를 돌려주고 Redis에도 남긴다."""
    st = get_settings()
    if not enabled(st):
        return {"status": "off"}
    now = now or datetime.now(UTC)
    prev = load_state() or {}
    state: dict[str, Any] = {
        "status": "ok",
        "checked_at": now.isoformat(),
        "last_success": prev.get("last_success"),
        "last_file": prev.get("last_file"),
        "uploaded": [],
        "deleted": 0,
        "message": "",
    }
    try:
        s3 = client or _client(st)
        bucket, prefix = st.genio_backup_s3_bucket, _prefix(st)
        folder = Path(st.genio_backup_dir)
        recent = now - timedelta(days=UPLOAD_RECENT_DAYS)
        local = sorted(
            f
            for f in (folder.iterdir() if folder.is_dir() else [])
            if DUMP_RE.match(f.name) and datetime.fromtimestamp(f.stat().st_mtime, UTC) >= recent
        )
        for f in local:
            key = prefix + f.name
            if _exists(s3, bucket, key):
                continue
            s3.upload_file(str(f), bucket, key)
            state["uploaded"].append(f.name)
            log.info("외부 백업 올림: %s (%.1fMB)", f.name, os.path.getsize(f) / 1048576)
        if local:
            state["last_file"] = local[-1].name
        state["last_success"] = now.isoformat()
        # 보관 기간이 지난 바깥 백업 지우기(우리가 올린 이름 모양만)
        cutoff = now - timedelta(days=max(1, st.genio_backup_s3_keep_days))
        token: str | None = None
        while True:
            kw: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            page = s3.list_objects_v2(**kw)
            for obj in page.get("Contents") or []:
                name = str(obj["Key"])[len(prefix) :]
                modified = obj.get("LastModified")
                if DUMP_RE.match(name) and modified is not None and modified < cutoff:
                    s3.delete_object(Bucket=bucket, Key=obj["Key"])
                    state["deleted"] += 1
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
    except Exception as exc:
        state["status"] = "error"
        state["message"] = f"외부 저장소에 백업을 올리지 못했어요({type(exc).__name__})."
        log.warning("외부 백업 실패: %s", type(exc).__name__)
    _save_state(state)
    return state
