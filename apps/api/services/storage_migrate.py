"""파일 저장소 옮기기(v0.8): DB에 있는 파일·문서 본문을 disk·s3로 옮기거나 DB로 되돌린다.

안전 규칙
- 옮길 때마다 저장소에 쓴 뒤 크기와 sha256을 다시 읽어 맞춰 보고, 맞을 때만 행을 바꾼다.
- 기본은 DB의 본문을 그대로 둔다(--clear-db를 줘야 비운다). 그래서 되돌리기가 쉽다.
- 이미 옮긴 행은 건너뛰므로 중간에 멈춰도 다시 돌리면 이어서 한다(배치마다 커밋).
- 저장소에 쓴 본문을 지우는 일은 하지 않는다(고아 파일 찾기는 report_orphans).
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import Document, StoredFile
from api.services import storage

log = logging.getLogger("genio.storage.migrate")

MODELS: dict[str, Any] = {"files": StoredFile, "documents": Document}
KINDS = {"files": "files", "documents": "documents"}


@dataclass
class Report:
    moved: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_moved: int = 0
    cleared: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "moved": self.moved,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_moved": self.bytes_moved,
            "cleared": self.cleared,
            "errors": self.errors[:20],
        }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_type(obj: Any) -> str | None:
    return getattr(obj, "mime", None)


def count_pending(db: Session, models: list[str]) -> int:
    total = 0
    for name in models:
        m = MODELS[name]
        total += int(
            db.scalar(
                select(func.count()).select_from(m).where(m.storage == storage.DB, m.size > 0)
            )
            or 0
        )
    return total


def _chunks(ids: list[str], n: int) -> list[list[str]]:
    return [ids[i : i + n] for i in range(0, len(ids), max(1, n))]


def migrate_to_storage(
    db: Session,
    target: str,
    *,
    models: list[str] | None = None,
    batch: int = 200,
    dry_run: bool = False,
    clear_db: bool = False,
    limit: int | None = None,
) -> Report:
    """DB(storage='db')에 있는 본문을 target 저장소(disk|s3)로 옮긴다."""
    if target not in (storage.DISK, storage.S3):
        raise ValueError("target은 disk 또는 s3여야 해요.")
    backend = storage.backend_named(target)
    rep = Report()
    for name in models or list(MODELS):
        m = MODELS[name]
        # 먼저 id만 모은다(시험 실행과 실제 실행이 같은 순서·같은 대상을 본다)
        ids = list(
            db.scalars(
                select(m.id).where(m.storage == storage.DB, m.size > 0).order_by(m.created_at, m.id)
            )
        )
        for group in _chunks(ids, batch):
            for row_id in group:
                if limit is not None and rep.moved + rep.failed >= limit:
                    db.commit()
                    return rep
                row = db.get(m, row_id)
                if row is None or row.storage != storage.DB:
                    rep.skipped += 1  # 그 사이 지워졌거나 이미 옮겼다
                    continue
                data = bytes(row.content or b"")
                if not data:
                    rep.skipped += 1  # 본문이 비어 있으면 옮길 것이 없다
                    continue
                if dry_run:
                    rep.moved += 1
                    rep.bytes_moved += len(data)
                    continue
                key = storage.new_key(KINDS[name])
                try:
                    backend.put(key, data, _content_type(row))
                    if backend.size(key) != len(data) or _sha(backend.get(key)) != _sha(data):
                        backend.delete(key)
                        raise ValueError("저장소에 쓴 내용이 원본과 달라요.")
                except Exception as exc:
                    rep.failed += 1
                    rep.errors.append(f"{name}:{row.id}: {type(exc).__name__}")
                    log.warning("옮기기 실패(%s %s)", name, row.id)
                    continue
                row.storage = target
                row.storage_key = key
                rep.moved += 1
                rep.bytes_moved += len(data)
                if clear_db:
                    row.content = storage.empty_value(row)
                    rep.cleared += 1
            if not dry_run:
                db.commit()  # 배치마다 커밋: 중간에 멈춰도 이어서 할 수 있다
    return rep


def restore_to_db(db: Session, *, models: list[str] | None = None, batch: int = 200) -> Report:
    """저장소(disk·s3)에 있는 본문을 DB로 되돌린다(storage='db'). 되돌리기 전용."""
    rep = Report()
    for name in models or list(MODELS):
        m = MODELS[name]
        ids = list(
            db.scalars(
                select(m.id)
                .where(m.storage != storage.DB, m.storage_key.is_not(None))
                .order_by(m.created_at, m.id)
            )
        )
        for group in _chunks(ids, batch):
            for row_id in group:
                row = db.get(m, row_id)
                if row is None or row.storage == storage.DB:
                    rep.skipped += 1
                    continue
                try:
                    data = storage.read_content(row)
                except Exception as exc:
                    rep.failed += 1
                    rep.errors.append(f"{name}:{row.id}: {type(exc).__name__}")
                    continue
                row.content = data
                row.storage = storage.DB
                row.storage_key = None
                rep.moved += 1
                rep.bytes_moved += len(data)
            db.commit()
    return rep


def report_orphans(
    db: Session, target: str, *, prefixes: tuple[str, ...] = ("files", "documents")
) -> list[str]:
    """저장소에는 있는데 어떤 행도 가리키지 않는 키(삭제하지 않고 보여 주기만 한다)."""
    backend = storage.backend_named(target)
    known: set[str] = set()
    for m in MODELS.values():
        known.update(
            k
            for k in db.scalars(
                select(m.storage_key).where(m.storage == target, m.storage_key.is_not(None))
            )
            if k
        )
    orphans: list[str] = []
    for prefix in prefixes:
        for key in backend.iter_keys(f"{prefix}/"):
            if key not in known:
                orphans.append(key)
    return orphans
