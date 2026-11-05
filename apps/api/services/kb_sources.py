"""v0.8 지식 가져오기 소스: 웹사이트·Notion·공개 Google 문서를 지식베이스에 연결하고 동기화한다.

소스 정의는 kb.settings["sources"] 목록(JSON)에 둔다. 가져온 문서는 Document로 저장하고, 어느 소스의
어느 쪽인지는 doc_metadata의 밑줄 키(_source_id·_source_key·_content_hash·_edited)로 기억한다
(밑줄 키는 화면·검색 결과에 보이지 않는다). 같은 쪽은 다시 가져와도 문서를 늘리지 않고,
내용이 바뀐 쪽만 다시 임베딩한다.
"""

import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.core.errors import AppError
from api.models import Document, KnowledgeBase
from api.services import kb_crawl, kb_google, kb_notion, storage
from api.services.kb_limits import check_write
from nodes import NodeError

log = logging.getLogger("genio.kb_sources")

SOURCE_TYPES = ("web", "notion", "google")
SCHEDULES = ("none", "daily")
MAX_SOURCES = 20
STALE_RUN = timedelta(minutes=20)
DAILY_AFTER = timedelta(hours=23)

SRC_ID = "_source_id"
SRC_KEY = "_source_key"
HASH = "_content_hash"
EDITED = "_edited"


def now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(text: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


@dataclass
class Incoming:
    key: str
    filename: str
    mime: str
    content: bytes
    hash: str
    url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Fetched:
    docs: list[Incoming] = field(default_factory=list)
    unchanged_keys: set[str] = field(default_factory=set)
    failed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------- 저장·조회 ----------------
def sources_of(kb: KnowledgeBase) -> list[dict[str, Any]]:
    raw = (kb.settings or {}).get("sources")
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


def find_source(kb: KnowledgeBase, sid: str) -> dict[str, Any] | None:
    return next((s for s in sources_of(kb) if s.get("id") == sid), None)


def _save_sources(kb: KnowledgeBase, sources: list[dict[str, Any]]) -> None:
    kb.settings = {**(kb.settings or {}), "sources": sources}


def update_source(
    db: Session, kb_id: str, sid: str, patch: dict[str, Any]
) -> dict[str, Any] | None:
    """소스 한 개의 값을 고쳐 저장한다(최신 값을 다시 읽어서 덮어쓴다)."""
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        return None
    db.refresh(kb)
    sources = sources_of(kb)
    for i, s in enumerate(sources):
        if s.get("id") == sid:
            sources[i] = {**s, **patch}
            _save_sources(kb, sources)
            db.commit()
            return sources[i]
    return None


def public_source(s: dict[str, Any]) -> dict[str, Any]:
    return dict(s)


# ---------------- 설정 확인 ----------------
def _str_list(raw: Any, limit: int, size: int = 200) -> list[str]:
    if isinstance(raw, str):
        raw = raw.replace(",", "\n").splitlines()
    if not isinstance(raw, list):
        return []
    return [str(x).strip()[:size] for x in raw if str(x).strip()][:limit]


def clean_config(db: Session, workspace_id: str, kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """종류별 설정을 확인하고 정리한다. 틀리면 두 줄 오류."""
    if kind == "web":
        url = str(raw.get("url") or "").strip()
        try:
            start = kb_crawl.validate_start(url)
        except (NodeError, ValueError) as exc:
            msg = exc.message if isinstance(exc, NodeError) else "웹 주소 형식이 올바르지 않아요."
            raise AppError(400, msg, "공개된 웹사이트 주소(https://…)인지 확인하세요.") from exc
        return {
            "url": start,
            "depth": max(0, min(int(raw.get("depth", 1) or 0), kb_crawl.MAX_DEPTH)),
            "max_pages": max(1, min(int(raw.get("max_pages", 20) or 20), kb_crawl.MAX_PAGES)),
            "include": _str_list(raw.get("include"), 20),
            "exclude": _str_list(raw.get("exclude"), 20),
        }
    if kind == "notion":
        cred = str(raw.get("credential_id") or "")
        if not cred:
            raise AppError(
                422,
                "노션 연결 정보를 골라 주세요.",
                "연결 정보 화면에서 노션 토큰을 먼저 등록하세요.",
            )
        try:
            kb_notion.token_of(db, workspace_id, cred)
        except NodeError as exc:
            raise AppError(422, exc.message, "연결 정보를 다시 골라 주세요.") from exc
        ids: list[str] = []
        for item in _str_list(raw.get("targets"), 20, 400):
            tid = kb_notion.parse_target(item)
            if tid is None:
                raise AppError(
                    422,
                    f"노션 주소나 id를 알아보지 못했어요: {item[:60]}",
                    "페이지를 열어 주소를 그대로 복사해 붙여 넣으세요.",
                )
            if tid not in ids:
                ids.append(tid)
        if not ids:
            raise AppError(
                422,
                "가져올 노션 페이지를 한 개 이상 넣어 주세요.",
                "페이지나 데이터베이스 주소를 넣으세요.",
            )
        return {
            "credential_id": cred,
            "targets": ids,
            "include_children": bool(raw.get("include_children")),
        }
    if kind == "google":
        urls = _str_list(raw.get("urls") or raw.get("url"), 20, 600)
        if not urls:
            raise AppError(
                422,
                "Google 문서 주소를 넣어 주세요.",
                "문서·시트·슬라이드의 공유 링크를 붙여 넣으세요.",
            )
        for u in urls:
            try:
                kb_google.parse_link(u)
            except NodeError as exc:
                raise AppError(422, exc.message, "공유 링크를 그대로 붙여 넣어 주세요.") from exc
        return {"urls": urls, "name": str(raw.get("name") or "").strip()[:200]}
    raise AppError(
        422, "알 수 없는 가져오기 종류예요.", "웹사이트·노션·Google 문서 중에서 고르세요."
    )


def default_name(kind: str, config: dict[str, Any]) -> str:
    if kind == "web":
        return str(config["url"])[:80]
    if kind == "notion":
        return f"노션 {len(config['targets'])}곳"
    return f"Google 문서 {len(config['urls'])}개"


def create_source(
    db: Session, kb: KnowledgeBase, kind: str, name: str, config: dict[str, Any], schedule: str
) -> dict[str, Any]:
    sources = sources_of(kb)
    if len(sources) >= MAX_SOURCES:
        raise AppError(
            409,
            f"가져오기 소스는 지식베이스마다 {MAX_SOURCES}개까지예요.",
            "안 쓰는 소스를 지우고 다시 추가하세요.",
        )
    src: dict[str, Any] = {
        "id": secrets.token_hex(6),
        "type": kind,
        "name": (name or default_name(kind, config)).strip()[:100],
        "config": config,
        "schedule": schedule if schedule in SCHEDULES else "none",
        "created_at": _iso(now()),
        "last_sync_at": None,
        "last_status": "new",
        "last_summary": None,
        "last_error": None,
        "running": False,
        "running_since": None,
        "progress": None,
    }
    sources.append(src)
    _save_sources(kb, sources)
    return src


def remove_source(kb: KnowledgeBase, sid: str, db: Session, delete_documents: bool) -> int:
    """소스를 지운다. delete_documents면 그 소스로 가져온 문서도 지운다. 지운 문서 수를 돌려준다."""
    sources = [s for s in sources_of(kb) if s.get("id") != sid]
    removed = 0
    if delete_documents:
        for d in db.scalars(select(Document).where(Document.kb_id == kb.id)):
            if (d.doc_metadata or {}).get(SRC_ID) == sid:
                db.delete(d)
                removed += 1
    _save_sources(kb, sources)
    return removed


# ---------------- 동기화 ----------------
def begin_sync(db: Session, kb: KnowledgeBase, sid: str) -> dict[str, Any]:
    """동기화를 시작한다고 표시한다(이미 도는 중이면 409). 실제 작업은 워커가 한다."""
    src = find_source(kb, sid)
    if src is None:
        raise AppError(
            404, "가져오기 소스를 찾을 수 없어요.", "목록을 새로고침한 뒤 다시 해 보세요."
        )
    started = _parse(src.get("running_since"))
    if src.get("running") and started and now() - started < STALE_RUN:
        raise AppError(
            409, "이미 가져오는 중이에요.", "끝날 때까지 기다린 뒤 다시 '지금 가져오기'를 누르세요."
        )
    patch = {"running": True, "running_since": _iso(now()), "progress": {"done": 0, "total": 0}}
    sources = [{**s, **patch} if s.get("id") == sid else s for s in sources_of(kb)]
    _save_sources(kb, sources)
    db.commit()
    return find_source(kb, sid) or src


def _existing_docs(db: Session, kb_id: str, sid: str) -> dict[str, Document]:
    out: dict[str, Document] = {}
    for d in db.scalars(select(Document).where(Document.kb_id == kb_id)):
        meta = d.doc_metadata or {}
        if meta.get(SRC_ID) == sid and meta.get(SRC_KEY):
            out[str(meta[SRC_KEY])] = d
    return out


def _fetch(db: Session, kb: KnowledgeBase, src: dict[str, Any], known: dict[str, str]) -> Fetched:
    sid = str(src["id"])
    cfg = src["config"]
    out = Fetched()
    delay = float(get_settings().genio_crawl_delay_seconds)

    def progress(done: int, total: int) -> None:
        update_source(db, kb.id, sid, {"progress": {"done": done, "total": total}})

    if src["type"] == "web":
        res = kb_crawl.crawl(
            cfg["url"],
            depth=cfg.get("depth", 1),
            max_pages=cfg.get("max_pages", 20),
            include=cfg.get("include") or [],
            exclude=cfg.get("exclude") or [],
            delay=delay,
            on_progress=progress,
        )
        for p in res.pages:
            out.docs.append(
                Incoming(
                    key=p.url,
                    filename=f"{p.title[:200]}.txt",
                    mime="text/plain",
                    content=p.text.encode("utf-8"),
                    hash=p.hash,
                    url=p.url,
                    extra={"source_url": p.url},
                )
            )
        out.failed = [f"{u[:80]} — {why}" for u, why in res.failed]
        if res.skipped_robots:
            out.notes.append(f"robots.txt가 막은 쪽 {res.skipped_robots}개는 건너뛰었어요.")
        if res.reached_limit:
            out.notes.append(f"쪽 수 한도({cfg.get('max_pages', 20)}쪽)에서 멈췄어요.")
        if not res.pages and not res.failed:
            raise NodeError("글이 있는 쪽을 찾지 못했어요. 주소와 허용·제외 패턴을 확인하세요.")
        return out
    if src["type"] == "notion":
        token = kb_notion.token_of(db, kb.workspace_id, str(cfg["credential_id"]))
        nres = kb_notion.fetch(
            token,
            list(cfg["targets"]),
            known=known,
            include_children=bool(cfg.get("include_children")),
            delay=min(delay + 0.04, 0.5) if delay > 0 else 0.0,
            on_progress=progress,
        )
        for page in nres.pages:
            if page.unchanged:
                out.unchanged_keys.add(page.id)
                continue
            out.docs.append(
                Incoming(
                    key=page.id,
                    filename=f"{page.title[:200]}.md",
                    mime="text/markdown",
                    content=page.markdown.encode("utf-8"),
                    hash=page.hash,
                    url=page.url or None,
                    extra={EDITED: page.last_edited},
                )
            )
        out.failed = [f"{k[:40]} — {why}" for k, why in nres.failed]
        if nres.reached_limit:
            out.notes.append(f"쪽 수 한도({kb_notion.MAX_PAGES}쪽)에서 멈췄어요.")
        if not nres.pages and nres.failed:
            raise NodeError(nres.failed[0][1])
        return out
    # google
    for i, url in enumerate(cfg["urls"]):
        try:
            doc = kb_google.fetch(url, name=cfg.get("name", "") if len(cfg["urls"]) == 1 else "")
        except NodeError as exc:
            out.failed.append(f"{url[:80]} — {exc.message}")
            continue
        out.docs.append(
            Incoming(
                key=doc.key,
                filename=doc.filename[:300],
                mime=doc.mime,
                content=doc.content,
                hash=doc.hash,
                url=doc.url[:2000],
                extra={"source_url": doc.url[:200]},
            )
        )
        progress(i + 1, len(cfg["urls"]))
    if not out.docs and out.failed:
        raise NodeError(out.failed[0].split(" — ", 1)[-1])
    return out


def sync_source(db: Session, kb_id: str, sid: str) -> dict[str, Any]:
    """소스를 지금 동기화한다(워커·시험에서 호출). 실패해도 예외를 밖으로 내지 않고 상태에 적는다."""
    from api.services.queue import enqueue_document

    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        return {}
    src = find_source(kb, sid)
    if src is None:
        return {}
    summary: dict[str, Any] = {"added": 0, "updated": 0, "unchanged": 0, "missing": 0, "failed": 0}
    status, error = "ok", None
    to_process: list[str] = []
    try:
        existing = _existing_docs(db, kb.id, sid)
        known = {
            k: str((d.doc_metadata or {}).get(EDITED) or "")
            for k, d in existing.items()
            if (d.doc_metadata or {}).get(EDITED) and d.status != "failed"
        }
        got = _fetch(db, kb, src, known)
        seen = set(got.unchanged_keys)
        for inc in got.docs:
            seen.add(inc.key)
            doc = existing.get(inc.key)
            meta = {SRC_ID: sid, SRC_KEY: inc.key, HASH: inc.hash, **inc.extra}
            if doc is not None:
                if (doc.doc_metadata or {}).get(HASH) == inc.hash and doc.status != "failed":
                    summary["unchanged"] += 1
                    continue
                check_write(db, kb.workspace_id, docs=0, size=max(0, len(inc.content) - doc.size))
                doc.filename = inc.filename
                doc.mime = inc.mime
                doc.size = len(inc.content)
                old_locs = storage.locations(
                    [doc]
                )  # 본문이 바뀌면 예전 저장소 파일은 커밋 뒤에 지운다
                storage.write_content(doc, inc.content, kind="documents", content_type=inc.mime)
                doc.url = inc.url
                doc.status = "uploaded"
                doc.error = None
                keep = {k: v for k, v in (doc.doc_metadata or {}).items() if not k.startswith("_")}
                doc.doc_metadata = {**keep, **meta}
                summary["updated"] += 1
            else:
                check_write(db, kb.workspace_id, docs=1, size=len(inc.content))
                doc = Document(
                    kb_id=kb.id,
                    filename=inc.filename,
                    mime=inc.mime,
                    size=len(inc.content),
                    status="uploaded",
                    source=str(src["type"]),
                    url=inc.url,
                    doc_metadata=meta,
                )
                storage.write_content(doc, inc.content, kind="documents", content_type=inc.mime)
                old_locs = []
                db.add(doc)
                existing[inc.key] = doc
                summary["added"] += 1
            db.commit()
            storage.purge(old_locs)
            to_process.append(doc.id)
        summary["unchanged"] += len(got.unchanged_keys)
        summary["missing"] = len([k for k in existing if k not in seen])
        summary["failed"] = len(got.failed)
        summary["notes"] = got.notes
        summary["failures"] = got.failed[:10]
        if got.failed:
            status = "partial"
    except NodeError as exc:
        db.rollback()
        status, error = "failed", exc.message
    except AppError as exc:
        db.rollback()
        status, error = "partial" if to_process else "failed", f"{exc.message} {exc.hint}"
    except Exception:
        db.rollback()
        log.exception("지식 가져오기 소스 동기화 오류(kb=%s source=%s)", kb_id, sid)
        status, error = "failed", "가져오는 중 문제가 생겼어요. 잠시 뒤 다시 시도하세요."
    finally:
        update_source(
            db,
            kb_id,
            sid,
            {
                "running": False,
                "running_since": None,
                "progress": None,
                "last_sync_at": _iso(now()),
                "last_status": status,
                "last_summary": summary,
                "last_error": error,
            },
        )
    for doc_id in to_process:
        try:
            enqueue_document(doc_id)
        except Exception:
            log.warning("문서 처리 예약 실패(doc=%s)", doc_id)
    kb2 = db.get(KnowledgeBase, kb_id)
    return (find_source(kb2, sid) if kb2 else None) or {}


def due_sources(db: Session) -> list[tuple[str, str]]:
    """'매일 동기화'로 정해 두고 하루가 지난 소스 목록(kb id, source id)."""
    out: list[tuple[str, str]] = []
    cutoff = now() - DAILY_AFTER
    for kb in db.scalars(select(KnowledgeBase)):
        for s in sources_of(kb):
            if s.get("schedule") != "daily" or s.get("running"):
                continue
            last = _parse(s.get("last_sync_at"))
            if last is None or last < cutoff:
                out.append((kb.id, str(s["id"])))
    return out
