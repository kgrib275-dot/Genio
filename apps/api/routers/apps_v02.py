"""v0.2 앱 기능: 기능 설정·환경 값·내보내기/가져오기/복제/되돌리기, 파일, 로그·주석·모니터링, API 키.
v0.4: 대화로 시험하기(작업본 챗 미리 보기)."""

import hashlib
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, or_, select

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.core.security import random_token
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import (
    Annotation,
    App,
    AppApiKey,
    Conversation,
    Message,
    Run,
    User,
    WorkflowVersion,
)
from api.routers.common import sse_frame, sse_response
from api.schemas.graph import Graph
from api.services import apps as svc
from api.services.app_config import merged_features, patch_features, store_env_vars
from api.services.chat import PREVIEW_PREFIX, ChatRequest, run_chat, start_chat
from api.services.files import save_upload

router = APIRouter(tags=["apps-v02"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]


def _not_preview_conv() -> ColumnElement[bool]:
    """'대화로 시험하기' 대화는 로그·통계에 넣지 않는다."""
    return or_(
        Conversation.external_session_id.is_(None),
        Conversation.external_session_id.not_like(f"{PREVIEW_PREFIX}%"),
    )


def _detail(ctx: Ctx, app: App) -> dict[str, Any]:
    return svc.app_detail(ctx.db, app)


# ---------------- 기능·환경 값 ----------------
@router.patch("/apps/{app_id}/features")
def update_features(app_id: str, body: dict[str, Any], ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    app.features = patch_features(app.features, body)
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.features",
        target_type="app",
        target_id=app.id,
    )
    ctx.db.commit()
    return _detail(ctx, app)


class EnvIn(BaseModel):
    env_vars: list[dict[str, Any]] = Field(max_length=50)


@router.put("/apps/{app_id}/env-vars")
def update_env(app_id: str, body: EnvIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    app.env_vars = store_env_vars(body.env_vars, app.env_vars or [])
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.env_vars",
        target_type="app",
        target_id=app.id,
        meta={"keys": [v["key"] for v in app.env_vars]},
    )
    ctx.db.commit()
    return _detail(ctx, app)


# ---------------- 내보내기·가져오기·복제·되돌리기 ----------------
@router.get("/apps/{app_id}/export")
def export_app(app_id: str, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    return {
        "genio_version": "0.2",
        "app": {
            "name": app.name,
            "type": app.type,
            "description": app.description,
            "icon": app.icon,
            "features": merged_features(app.features),
        },
        "graph": app.draft_graph or {},
        "env_vars": [
            {"key": v["key"], "value": v.get("value", ""), "secret": False}
            for v in (app.env_vars or [])
            if not v.get("secret")
        ]
        + [
            {"key": v["key"], "value": "", "secret": True}
            for v in (app.env_vars or [])
            if v.get("secret")
        ],
    }


class ImportIn(BaseModel):
    genio_version: str = "0.2"
    app: dict[str, Any]
    graph: dict[str, Any]
    env_vars: list[dict[str, Any]] = Field(default_factory=list)
    project_id: str | None = None


@router.post("/workspaces/{ws}/apps/import", status_code=201)
def import_app(ws: str, body: ImportIn, ctx: WsBuilders) -> dict[str, Any]:
    from api.routers.projects import check_project_target

    check_project_target(ctx, ws, body.project_id)
    try:
        graph = Graph.model_validate(body.graph).dump()
    except ValueError as exc:
        raise AppError(
            422,
            "가져올 파일의 흐름 형식이 올바르지 않아요.",
            "Genio에서 내보낸 JSON 파일인지 확인하세요.",
        ) from exc
    meta = body.app
    app_type = str(meta.get("type") or "workflow")
    if app_type not in ("chat", "workflow", "form"):
        app_type = "workflow"
    app = App(
        workspace_id=ws,
        name=str(meta.get("name") or "가져온 앱")[:100],
        slug=svc.slugify(str(meta.get("name") or "app")),
        type=app_type,
        description=str(meta.get("description") or "")[:2000],
        icon=str(meta.get("icon") or "")[:40],
        status="draft",
        created_by=ctx.user.id,
        draft_graph=graph,
        features=patch_features({}, dict(meta.get("features") or {})),
        env_vars=store_env_vars(body.env_vars, []),
        project_id=body.project_id or None,
    )
    ctx.db.add(app)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="app.import",
        target_type="app",
        target_id=app.id,
        meta={"name": app.name},
    )
    ctx.db.commit()
    return _detail(ctx, app)


@router.post("/apps/{app_id}/duplicate", status_code=201)
def duplicate_app(app_id: str, ctx: AppBuilders) -> dict[str, Any]:
    src = svc.get_app(ctx.db, app_id)
    app = App(
        workspace_id=src.workspace_id,
        name=f"{src.name} (복사본)"[:100],
        slug=svc.slugify(src.name),
        type=src.type,
        description=src.description,
        icon=src.icon,
        status="draft",
        created_by=ctx.user.id,
        draft_graph=src.draft_graph,
        features=dict(src.features or {}),
        env_vars=list(src.env_vars or []),
    )
    ctx.db.add(app)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=src.workspace_id,
        user_id=ctx.user.id,
        action="app.duplicate",
        target_type="app",
        target_id=app.id,
        meta={"from": src.id},
    )
    ctx.db.commit()
    return _detail(ctx, app)


@router.post("/apps/{app_id}/versions/{version}/restore")
def restore_version(app_id: str, version: int, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    v = ctx.db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.app_id == app_id, WorkflowVersion.version == version
        )
    )
    if v is None:
        raise not_found("버전")
    app.draft_graph = v.graph
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.version_restore",
        target_type="app",
        target_id=app.id,
        meta={"version": version},
    )
    ctx.db.commit()
    return _detail(ctx, app)


# ---------------- 파일 ----------------
@router.post("/workspaces/{ws}/files")
async def upload_file(
    ws: str, ctx: WsBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    return await save_upload(ctx.db, ws, file, user_id=ctx.user.id)


# ---------------- 로그 ----------------
@router.get("/apps/{app_id}/conversations")
def list_conversations(
    app_id: str,
    ctx: AppViewers,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, pattern="^(bot|handoff|closed)$"),
) -> list[dict[str, Any]]:
    stmt = select(Conversation).where(Conversation.app_id == app_id, _not_preview_conv())
    if status:
        # v0.5 상담원 응대함: handoff = 사람이 답해야 하는 대화
        stmt = stmt.where(Conversation.status == status)
    if q and q.strip():
        # 대화 안의 메시지 내용으로 찾는다
        hit = (
            select(Message.conversation_id)
            .where(Message.content.ilike(f"%{q.strip()}%"))
            .distinct()
        )
        stmt = stmt.where(Conversation.id.in_(hit))
    convs = list(
        ctx.db.scalars(
            stmt.order_by(Conversation.created_at.desc()).offset((page - 1) * size).limit(size)
        )
    )
    ids = [c.id for c in convs]
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "likes": 0, "dislikes": 0, "last": None, "first_q": ""}
    )
    if ids:
        for m in ctx.db.scalars(
            select(Message).where(Message.conversation_id.in_(ids)).order_by(Message.created_at)
        ):
            st = stats[m.conversation_id]
            st["n"] += 1
            st["last"] = m.created_at
            if m.role == "user" and not st["first_q"]:
                st["first_q"] = m.content[:120]
            if m.feedback == "like":
                st["likes"] += 1
            elif m.feedback == "dislike":
                st["dislikes"] += 1
    users = {
        u.id: u.name
        for u in ctx.db.scalars(
            select(User).where(User.id.in_([c.user_id for c in convs if c.user_id]))
        )
    }
    return [
        {
            "id": c.id,
            "user_name": users.get(c.user_id or "", "방문자"),
            "external_session_id": c.external_session_id,
            "message_count": stats[c.id]["n"],
            "likes": stats[c.id]["likes"],
            "dislikes": stats[c.id]["dislikes"],
            "created_at": c.created_at,
            "last_message_at": stats[c.id]["last"],
            "first_question": stats[c.id]["first_q"],
            "status": c.status,
        }
        for c in convs
    ]


ConvViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="conversation"))]


@router.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: str, ctx: ConvViewers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "run_id": m.run_id,
            "feedback": m.feedback,
            "feedback_comment": m.feedback_comment,
            "created_at": m.created_at,
            "annotated": m.annotation_id is not None,
            "moderated": m.moderated,
            "citations": m.citations or [],
            "latency_ms": m.latency_ms,
        }
        for m in rows
    ]


# ---------------- 주석 ----------------
def _ann(a: Annotation) -> dict[str, Any]:
    return {
        "id": a.id,
        "question": a.question,
        "answer": a.answer,
        "hit_count": a.hit_count,
        "created_at": a.created_at,
    }


class AnnotationIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)


class AnnotationPatch(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=2000)
    answer: str | None = Field(default=None, min_length=1, max_length=8000)


@router.get("/apps/{app_id}/annotations")
def list_annotations(app_id: str, ctx: AppBuilders) -> list[dict[str, Any]]:
    return [
        _ann(a)
        for a in ctx.db.scalars(
            select(Annotation)
            .where(Annotation.app_id == app_id)
            .order_by(Annotation.created_at.desc())
        )
    ]


@router.post("/apps/{app_id}/annotations", status_code=201)
def create_annotation(app_id: str, body: AnnotationIn, ctx: AppBuilders) -> dict[str, Any]:
    a = Annotation(
        app_id=app_id,
        question=body.question.strip(),
        answer=body.answer.strip(),
        created_by=ctx.user.id,
    )
    ctx.db.add(a)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="annotation.create",
        target_type="annotation",
        target_id=a.id,
    )
    ctx.db.commit()
    return _ann(a)


AnnBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="annotation"))]


@router.patch("/annotations/{annotation_id}")
def update_annotation(
    annotation_id: str, body: AnnotationPatch, ctx: AnnBuilders
) -> dict[str, Any]:
    a = ctx.db.get(Annotation, annotation_id)
    if a is None:
        raise not_found("주석")
    if body.question is not None:
        a.question = body.question.strip()
    if body.answer is not None:
        a.answer = body.answer.strip()
    ctx.db.commit()
    return _ann(a)


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: str, ctx: AnnBuilders) -> Response:
    a = ctx.db.get(Annotation, annotation_id)
    if a is None:
        raise not_found("주석")
    ctx.db.delete(a)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="annotation.delete",
        target_type="annotation",
        target_id=annotation_id,
    )
    ctx.db.commit()
    return Response(status_code=204)


# ---------------- 모니터링 ----------------
def _day(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).date().isoformat()


@router.get("/apps/{app_id}/stats")
def app_stats(
    app_id: str, ctx: AppViewers, days: int = Query(default=7, ge=1, le=90)
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days - 1)
    since = since.replace(hour=0, minute=0, second=0, microsecond=0)
    keys = [(since + timedelta(days=i)).date().isoformat() for i in range(days)]
    rows: dict[str, dict[str, Any]] = {
        k: {
            "date": k,
            "runs": 0,
            "succeeded": 0,
            "conversations": 0,
            "messages": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": Decimal(0),
            "latencies": [],
            "likes": 0,
            "dislikes": 0,
        }
        for k in keys
    }
    for r in ctx.db.scalars(
        select(Run).where(Run.app_id == app_id, Run.created_at >= since, Run.trigger != "preview")
    ):
        d = rows.get(_day(r.created_at))
        if d is None:
            continue
        d["runs"] += 1
        d["succeeded"] += 1 if r.status == "succeeded" else 0
        u = r.token_usage or {}
        d["input_tokens"] += int(u.get("input_tokens", 0))
        d["output_tokens"] += int(u.get("output_tokens", 0))
        d["cost"] += Decimal(str(r.cost or 0))
        if r.started_at and r.finished_at:
            d["latencies"].append((r.finished_at - r.started_at).total_seconds() * 1000)
    for c in ctx.db.scalars(
        select(Conversation).where(
            Conversation.app_id == app_id, Conversation.created_at >= since, _not_preview_conv()
        )
    ):
        d = rows.get(_day(c.created_at))
        if d is not None:
            d["conversations"] += 1
    msgs = ctx.db.execute(
        select(Message.created_at, Message.role, Message.feedback)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.app_id == app_id, Message.created_at >= since, _not_preview_conv())
    ).all()
    for created, _role, fb in msgs:
        d = rows.get(_day(created))
        if d is None:
            continue
        d["messages"] += 1
        d["likes"] += 1 if fb == "like" else 0
        d["dislikes"] += 1 if fb == "dislike" else 0

    def finish(d: dict[str, Any]) -> dict[str, Any]:
        lat = d.pop("latencies")
        succeeded = d.pop("succeeded")
        d["avg_latency_ms"] = round(sum(lat) / len(lat)) if lat else 0
        d["success_rate"] = round(succeeded / d["runs"], 3) if d["runs"] else None
        d["cost"] = float(d["cost"])
        return d

    out_days = [finish(rows[k]) for k in keys]
    totals: dict[str, Any] = {
        k: sum(d[k] for d in out_days)
        for k in (
            "runs",
            "conversations",
            "messages",
            "input_tokens",
            "output_tokens",
            "likes",
            "dislikes",
        )
    }
    totals["cost"] = round(sum(d["cost"] for d in out_days), 6)
    lat_days = [d["avg_latency_ms"] for d in out_days if d["runs"]]
    totals["avg_latency_ms"] = round(sum(lat_days) / len(lat_days)) if lat_days else 0
    ok = (
        ctx.db.scalar(
            select(func.count())
            .select_from(Run)
            .where(
                Run.app_id == app_id,
                Run.created_at >= since,
                Run.status == "succeeded",
                Run.trigger != "preview",
            )
        )
        or 0
    )
    totals["success_rate"] = round(ok / totals["runs"], 3) if totals["runs"] else None
    return {"days": out_days, "totals": totals}


# ---------------- API 키 ----------------
KEY_PREFIX = "gk-"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _key(k: AppApiKey) -> dict[str, Any]:
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "scopes": list(k.scopes or ["chat", "run"]),
    }


KEY_SCOPES = ("chat", "run", "logs")
KeyScope = Literal["chat", "run", "logs"]


def _default_scopes() -> list[KeyScope]:
    return ["chat", "run"]


class KeyIn(BaseModel):
    name: str = Field(default="기본 키", min_length=1, max_length=100)
    # 권한 범위: chat(대화) · run(흐름 실행) · logs(실행 기록 읽기)
    scopes: list[KeyScope] = Field(default_factory=_default_scopes, min_length=1, max_length=3)


@router.get("/apps/{app_id}/api-keys")
def list_keys(app_id: str, ctx: AppBuilders) -> list[dict[str, Any]]:
    return [
        _key(k)
        for k in ctx.db.scalars(
            select(AppApiKey).where(AppApiKey.app_id == app_id).order_by(AppApiKey.created_at)
        )
    ]


@router.post("/apps/{app_id}/api-keys", status_code=201)
def create_key(app_id: str, body: KeyIn, ctx: AppBuilders) -> dict[str, Any]:
    if (
        ctx.db.scalar(select(func.count()).select_from(AppApiKey).where(AppApiKey.app_id == app_id))
        or 0
    ) >= 10:
        raise AppError(
            409, "API 키는 앱마다 10개까지 만들 수 있어요.", "쓰지 않는 키를 지운 뒤 다시 만드세요."
        )
    raw = KEY_PREFIX + random_token(24)
    k = AppApiKey(
        app_id=app_id,
        name=body.name,
        prefix=raw[:10] + "…",
        key_hash=hash_key(raw),
        created_by=ctx.user.id,
        scopes=[s for s in KEY_SCOPES if s in set(body.scopes)],
    )
    ctx.db.add(k)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="api_key.create",
        target_type="app",
        target_id=app_id,
        meta={"name": body.name, "prefix": k.prefix, "scopes": k.scopes},
    )
    ctx.db.commit()
    return {**_key(k), "key": raw}


KeyBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="api_key"))]


@router.delete("/api-keys/{key_id}", status_code=204)
def delete_key(key_id: str, ctx: KeyBuilders) -> Response:
    k = ctx.db.get(AppApiKey, key_id)
    if k is None:
        raise not_found("API 키")
    ctx.db.delete(k)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="api_key.delete",
        target_type="app",
        target_id=k.app_id,
        meta={"prefix": k.prefix},
    )
    ctx.db.commit()
    return Response(status_code=204)


# ---------------- 대화로 시험하기(v0.4) ----------------
class PreviewChatIn(BaseModel):
    message: str = Field(default="", max_length=4000)
    session_id: str | None = Field(default=None, max_length=100)
    input: dict[str, Any] | None = None


@router.post("/apps/{app_id}/preview/chat")
def preview_chat(app_id: str, body: PreviewChatIn, ctx: AppBuilders) -> StreamingResponse:
    """작업본 그래프로 대화해 본다. 공개 챗과 같은 SSE 이벤트, 로그·통계에는 넣지 않는다."""
    app = svc.get_app(ctx.db, app_id)
    graph = app.draft_graph or {}
    result = svc.validate_for_app(ctx.db, app, graph)
    if not result.valid:
        raise AppError(
            422,
            "흐름에 고칠 부분이 있어 대화해 볼 수 없어요.",
            "빨간 테두리 단계의 오류를 먼저 고치세요.",
            errors=[e.model_dump() for e in result.errors],
        )
    req = ChatRequest(
        app=app,
        version=None,
        deployment=None,
        user_id=ctx.user.id,
        message=body.message,
        session_id=body.session_id,
        inputs=dict(body.input or {}),
        trigger="preview",
    )
    conv, _ = start_chat(ctx.db, req)
    conv_id, session_id, user_id = conv.id, conv.external_session_id or "", ctx.user.id
    message, inputs = body.message, dict(body.input or {})

    def frames() -> Iterator[str]:
        yield sse_frame("session", {"session_id": session_id})
        for name, data in run_chat(
            conv_id,
            app_id,
            None,
            user_id,
            message,
            inputs,
            [],
            trigger="preview",
            draft_graph=graph,
        ):
            yield sse_frame(name, data)

    return sse_response(frames())


# ---------------- v0.5 상담원 전환(기능 정의서 S7) ----------------
ConvOperators = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="conversation"))]


class AgentReplyIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.post("/conversations/{conversation_id}/reply", status_code=201)
def agent_reply(conversation_id: str, body: AgentReplyIn, ctx: ConvOperators) -> dict[str, Any]:
    """상담원이 방문자에게 답한다(방문자 챗 화면이 주기적으로 읽어 보여 준다)."""
    conv = ctx.db.get(Conversation, conversation_id)
    if conv is None:
        raise not_found("대화")
    if conv.status != "handoff":
        raise AppError(
            409,
            "상담원 연결 중인 대화가 아니에요.",
            "방문자가 상담원 연결을 요청한 대화에만 답할 수 있어요.",
        )
    conv.assigned_to = conv.assigned_to or ctx.user.id
    m = Message(conversation_id=conv.id, role="agent", content=body.content.strip())
    ctx.db.add(m)
    ctx.db.commit()
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at,
        "agent_name": ctx.user.name,
    }


@router.post("/conversations/{conversation_id}/close")
def close_handoff(conversation_id: str, ctx: ConvOperators) -> dict[str, Any]:
    """상담을 마친다. 다음 메시지부터 다시 챗봇이 답한다."""
    conv = ctx.db.get(Conversation, conversation_id)
    if conv is None:
        raise not_found("대화")
    if conv.status == "handoff":
        conv.status = "closed"
        ctx.db.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="상담원 연결이 끝났어요. 이어서 물어보시면 챗봇이 답해 드릴게요.",
            )
        )
        app = ctx.db.get(App, conv.app_id)
        audit(
            ctx.db,
            workspace_id=app.workspace_id if app else None,
            user_id=ctx.user.id,
            action="conversation.close",
            target_type="conversation",
            target_id=conv.id,
        )
        ctx.db.commit()
    return {"id": conv.id, "status": conv.status}
