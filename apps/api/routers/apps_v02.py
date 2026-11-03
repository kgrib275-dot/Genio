"""v0.2 앱 기능: 기능 설정·환경 변수·내보내기/가져오기/복제/되돌리기, 파일, 로그·주석·모니터링, API 키."""

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

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
from api.schemas.graph import Graph
from api.services import apps as svc
from api.services.app_config import merged_features, patch_features, store_env_vars
from api.services.files import save_upload

router = APIRouter(tags=["apps-v02"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]


def _detail(ctx: Ctx, app: App) -> dict[str, Any]:
    return svc.app_detail(ctx.db, app)


# ---------------- 기능·환경 변수 ----------------
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


@router.post("/workspaces/{ws}/apps/import", status_code=201)
def import_app(ws: str, body: ImportIn, ctx: WsBuilders) -> dict[str, Any]:
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
    app_id: str, ctx: AppViewers, page: int = Query(default=1, ge=1)
) -> list[dict[str, Any]]:
    size = 30
    convs = list(
        ctx.db.scalars(
            select(Conversation)
            .where(Conversation.app_id == app_id)
            .order_by(Conversation.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
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
    for r in ctx.db.scalars(select(Run).where(Run.app_id == app_id, Run.created_at >= since)):
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
        select(Conversation).where(Conversation.app_id == app_id, Conversation.created_at >= since)
    ):
        d = rows.get(_day(c.created_at))
        if d is not None:
            d["conversations"] += 1
    msgs = ctx.db.execute(
        select(Message.created_at, Message.role, Message.feedback)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.app_id == app_id, Message.created_at >= since)
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
            .where(Run.app_id == app_id, Run.created_at >= since, Run.status == "succeeded")
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
    }


class KeyIn(BaseModel):
    name: str = Field(default="기본 키", min_length=1, max_length=100)


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
    )
    ctx.db.add(k)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="api_key.create",
        target_type="app",
        target_id=app_id,
        meta={"name": body.name, "prefix": k.prefix},
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
