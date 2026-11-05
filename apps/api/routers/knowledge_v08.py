"""v0.8 지식베이스: 가져오기 소스(웹사이트·Notion·공개 Google 문서), 외부 지식베이스 연결 시험,
검색 튜닝(대표 질문 세트), 지식 사용 한도. docs/api.md '## v0.8 지식 데이터 소스…' 참고."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import KnowledgeBase, Workspace
from api.routers.knowledge import ExternalIn
from api.services import kb_external, kb_limits, kb_sources, kb_tuning
from api.services import knowledge as svc
from api.services.queue import enqueue_source_sync

router = APIRouter(tags=["knowledge-v08"])
WsViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
WsManagers = Annotated[Ctx, Depends(require_role(("owner", "admin")))]
KbViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="kb"))]
KbBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="kb"))]


def _kb(ctx: Ctx, kb_id: str) -> KnowledgeBase:
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    return kb


def internal_kb(ctx: Ctx, kb_id: str) -> KnowledgeBase:
    """문서를 올리거나 가져오는 기능은 일반 지식베이스에서만 쓴다."""
    kb = _kb(ctx, kb_id)
    if svc.kb_settings(kb)["kind"] == "external":
        raise AppError(
            409,
            "외부 지식베이스에는 문서를 올릴 수 없어요.",
            "문서는 연결한 외부 서비스에서 관리하세요.",
        )
    return kb


# ---------------- 가져오기 소스 ----------------
class SourceIn(BaseModel):
    type: Literal["web", "notion", "google"]
    name: str = Field(default="", max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule: Literal["none", "daily"] = "none"
    sync_now: bool = True


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] | None = None
    schedule: Literal["none", "daily"] | None = None


def _out(src: dict[str, Any]) -> dict[str, Any]:
    return kb_sources.public_source(src)


@router.get("/knowledge-bases/{kb_id}/sources")
def list_sources(kb_id: str, ctx: KbViewers) -> list[dict[str, Any]]:
    return [_out(s) for s in kb_sources.sources_of(_kb(ctx, kb_id))]


@router.post("/knowledge-bases/{kb_id}/sources", status_code=201)
def add_source(kb_id: str, body: SourceIn, ctx: KbBuilders) -> dict[str, Any]:
    kb = internal_kb(ctx, kb_id)
    config = kb_sources.clean_config(ctx.db, kb.workspace_id, body.type, body.config)
    # 한도는 올리기 전에 한 번 확인한다(가져오는 동안에는 문서마다 다시 확인한다)
    kb_limits.check_write(ctx.db, kb.workspace_id, docs=1, size=0)
    src = kb_sources.create_source(ctx.db, kb, body.type, body.name, config, body.schedule)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.source_create",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"type": body.type, "name": src["name"]},
    )
    ctx.db.commit()
    if body.sync_now:
        src = kb_sources.begin_sync(ctx.db, kb, src["id"])
        enqueue_source_sync(kb.id, src["id"])
        ctx.db.expire_all()
        src = kb_sources.find_source(_kb(ctx, kb_id), src["id"]) or src
    return _out(src)


@router.patch("/knowledge-bases/{kb_id}/sources/{sid}")
def patch_source(kb_id: str, sid: str, body: SourcePatch, ctx: KbBuilders) -> dict[str, Any]:
    kb = internal_kb(ctx, kb_id)
    src = kb_sources.find_source(kb, sid)
    if src is None:
        raise not_found("가져오기 소스")
    patch: dict[str, Any] = {}
    if body.name is not None and body.name.strip():
        patch["name"] = body.name.strip()[:100]
    if body.schedule is not None:
        patch["schedule"] = body.schedule
    if body.config is not None:
        patch["config"] = kb_sources.clean_config(
            ctx.db, kb.workspace_id, str(src["type"]), {**src["config"], **body.config}
        )
    updated = kb_sources.update_source(ctx.db, kb.id, sid, patch)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.source_update",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"source": sid},
    )
    ctx.db.commit()
    return _out(updated or src)


@router.delete("/knowledge-bases/{kb_id}/sources/{sid}", status_code=204)
def delete_source(
    kb_id: str, sid: str, ctx: KbBuilders, delete_documents: Annotated[bool, Query()] = False
) -> Response:
    kb = internal_kb(ctx, kb_id)
    if kb_sources.find_source(kb, sid) is None:
        raise not_found("가져오기 소스")
    removed = kb_sources.remove_source(kb, sid, ctx.db, delete_documents)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.source_delete",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"source": sid, "documents_removed": removed},
    )
    ctx.db.commit()
    return Response(status_code=204)


@router.post("/knowledge-bases/{kb_id}/sources/{sid}/sync", status_code=202)
def sync_source_now(kb_id: str, sid: str, ctx: KbBuilders) -> dict[str, Any]:
    kb = internal_kb(ctx, kb_id)
    src = kb_sources.begin_sync(ctx.db, kb, sid)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.source_sync",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"source": sid},
    )
    ctx.db.commit()
    enqueue_source_sync(kb.id, sid)
    ctx.db.expire_all()
    return _out(kb_sources.find_source(_kb(ctx, kb_id), sid) or src)


# ---------------- 외부 지식베이스 ----------------
class ExternalTestIn(ExternalIn):
    query: str = Field(default="연결 시험", min_length=1, max_length=200)


def clean_external(ctx_db: Any, workspace_id: str, body: ExternalIn) -> dict[str, Any]:
    """외부 지식베이스 설정을 확인하고 정리한다(연결 정보는 이 워크스페이스의 HTTP 인증 정보만)."""
    from api.connectors.http_auth import CREDENTIAL_KEY
    from api.models import ConnectorCredential, ConnectorDefinition

    cred = (body.credential_id or "").strip()
    if cred:
        row = ctx_db.get(ConnectorCredential, cred)
        d = ctx_db.get(ConnectorDefinition, row.definition_id) if row is not None else None
        if row is None or row.workspace_id != workspace_id or d is None or d.key != CREDENTIAL_KEY:
            raise AppError(
                422,
                "고른 연결 정보를 쓸 수 없어요.",
                "연결 정보 화면에서 'HTTP 인증 정보'를 만들어 API 키를 넣고 다시 고르세요.",
            )
    return {
        "endpoint": kb_external.clean_endpoint(body.endpoint),
        "knowledge_id": body.knowledge_id.strip(),
        "credential_id": cred or None,
    }


@router.post("/workspaces/{ws}/knowledge-bases/external/test")
def test_new_external(ws: str, body: ExternalTestIn, ctx: WsBuilders) -> dict[str, Any]:
    """저장하기 전에 외부 지식베이스에 연결해 본다."""
    ext = clean_external(ctx.db, ws, body)
    return kb_external.test_connection(ctx.db, ws, ext, body.query)


@router.post("/knowledge-bases/{kb_id}/external/test")
def test_saved_external(kb_id: str, ctx: KbBuilders) -> dict[str, Any]:
    kb = _kb(ctx, kb_id)
    ext = kb_external.external_of(kb)
    if ext is None:
        raise AppError(409, "외부 지식베이스가 아니에요.", "일반 지식베이스는 검색 시험을 쓰세요.")
    return kb_external.test_connection(ctx.db, kb.workspace_id, ext)


@router.put("/knowledge-bases/{kb_id}/external")
def update_external(kb_id: str, body: ExternalIn, ctx: KbBuilders) -> dict[str, Any]:
    kb = _kb(ctx, kb_id)
    if kb_external.external_of(kb) is None:
        raise AppError(409, "외부 지식베이스가 아니에요.", "일반 지식베이스는 설정 화면을 쓰세요.")
    ext = clean_external(ctx.db, kb.workspace_id, body)
    kb.settings = {**(kb.settings or {}), "external": ext}
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.external_update",
        target_type="knowledge_base",
        target_id=kb.id,
    )
    ctx.db.commit()
    return ext


# ---------------- 검색 튜닝 ----------------
class QuestionIn(BaseModel):
    id: str | None = Field(default=None, max_length=16)
    question: str = Field(min_length=1, max_length=300)
    expect_keyword: str = Field(default="", max_length=100)
    expect_document_id: str = Field(default="", max_length=64)


class QuestionsIn(BaseModel):
    questions: list[QuestionIn] = Field(max_length=kb_tuning.MAX_QUESTIONS)


class RunIn(BaseModel):
    include_rerank: bool = False
    # 재정렬은 AI를 질문마다 더 부른다. 비용을 알고 켠다는 확인이 있어야 한다.
    confirm_rerank: bool = False


def _tunable(ctx: Ctx, kb_id: str) -> KnowledgeBase:
    kb = internal_kb(ctx, kb_id)
    return kb


@router.get("/knowledge-bases/{kb_id}/tuning")
def get_tuning(kb_id: str, ctx: KbViewers) -> dict[str, Any]:
    kb = _tunable(ctx, kb_id)
    t = kb_tuning.tuning_of(kb)
    return {
        **t,
        "estimate": kb_tuning.estimate(len(t["questions"])),
        "current": svc.kb_settings(kb)["retrieval"],
        "max_questions": kb_tuning.MAX_QUESTIONS,
    }


@router.put("/knowledge-bases/{kb_id}/tuning/questions")
def put_questions(kb_id: str, body: QuestionsIn, ctx: KbBuilders) -> dict[str, Any]:
    kb = _tunable(ctx, kb_id)
    cleaned = kb_tuning.clean_questions(ctx.db, kb.id, [q.model_dump() for q in body.questions])
    kb_tuning.save_questions(kb, cleaned)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.tuning_questions",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"count": len(cleaned)},
    )
    ctx.db.commit()
    return {"questions": cleaned, "estimate": kb_tuning.estimate(len(cleaned))}


@router.post("/knowledge-bases/{kb_id}/tuning/run")
def run_tuning(kb_id: str, body: RunIn, ctx: KbBuilders) -> dict[str, Any]:
    kb = _tunable(ctx, kb_id)
    if body.include_rerank and not body.confirm_rerank:
        n = len(kb_tuning.tuning_of(kb)["questions"])
        raise AppError(
            422,
            f"재정렬을 켜면 AI를 약 {n * len(kb_tuning.METHODS)}번 더 불러 비용이 들어요.",
            "비용을 확인했다면 '비용을 알고 실행'을 체크한 뒤 다시 실행하세요.",
        )
    result = kb_tuning.run(ctx.db, kb, include_rerank=body.include_rerank)
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.tuning_run",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"questions": result["questions"], "rerank": body.include_rerank},
    )
    ctx.db.commit()
    return result


# ---------------- 사용 한도 ----------------
class LimitsIn(BaseModel):
    max_documents: int | None = Field(default=None, ge=0, le=kb_limits.UPPER["max_documents"])
    max_total_mb: int | None = Field(default=None, ge=0, le=kb_limits.UPPER["max_total_mb"])
    max_writes_per_min: int | None = Field(
        default=None, ge=0, le=kb_limits.UPPER["max_writes_per_min"]
    )


@router.get("/workspaces/{ws}/knowledge/usage")
def knowledge_usage(ws: str, ctx: WsViewers) -> dict[str, Any]:
    snap = kb_limits.snapshot(ctx.db, ws)
    snap["can_edit"] = ctx.role in ("owner", "admin")
    snap["labels"] = kb_limits.LABEL
    return snap


@router.put("/workspaces/{ws}/knowledge/limits")
def set_knowledge_limits(ws: str, body: LimitsIn, ctx: WsManagers) -> dict[str, Any]:
    workspace = ctx.db.get(Workspace, ws)
    if workspace is None:
        raise not_found("워크스페이스")
    limits = kb_limits.set_limits(workspace, body.model_dump())
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="kb.limits_update",
        target_type="workspace",
        target_id=ws,
        meta=limits,
    )
    ctx.db.commit()
    return {"limits": limits, "usage": kb_limits.usage(ctx.db, ws)}
