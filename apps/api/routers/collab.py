"""동시 편집·댓글(v0.9): 접속 표시, 실시간 알림 스트림, 캔버스 댓글.

권한: 접속 표시·댓글 읽기는 빌더를 열 수 있는 역할(소유자·관리자·제작자·운영자),
댓글 쓰기·해결은 앱을 고칠 수 있는 역할(소유자·관리자·제작자).
"""

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.engine import app_bus
from api.models import CanvasComment, Membership, User
from api.routers.common import public_origin, sse_frame, sse_response
from api.services import apps as app_svc
from api.services import collab, presence

router = APIRouter(tags=["collab"])
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]

STREAM_MAX_SECONDS = 3600
KEEPALIVE_SECONDS = 15.0
PRESENCE_REFRESH_SECONDS = 10.0
MAX_COMMENTS_PER_APP = 2000


def _now() -> datetime:
    return datetime.now(UTC)


def _client_id(request: Request) -> str | None:
    return (request.headers.get("x-genio-client") or "")[:64] or None


# ---------------- 접속 표시 ----------------
class PresenceIn(BaseModel):
    node_id: str | None = Field(default=None, max_length=64)
    editing: bool = False
    leave: bool = False


def _publish_presence(app_id: str) -> list[dict[str, Any]]:
    users = presence.public_view(presence.snapshot(app_id))
    app_bus.publish(app_id, "presence", {"users": users})
    return users


@router.post("/apps/{app_id}/presence")
def post_presence(app_id: str, body: PresenceIn, ctx: AppViewers) -> dict[str, Any]:
    """10초마다 '나 여기 있어요'를 알린다. 어떤 단계를 보는지·고치는 중인지도 함께."""
    if body.leave:
        presence.drop(app_id, ctx.user.id)
    else:
        presence.touch(
            app_id,
            ctx.user.id,
            ctx.user.name,
            node_id=body.node_id,
            editing=body.editing,
            can_edit=ctx.role in EDIT_APPS,
        )
    return {"users": _publish_presence(app_id)}


@router.get("/apps/{app_id}/presence")
def get_presence(app_id: str, ctx: AppViewers) -> dict[str, Any]:
    return {"users": presence.public_view(presence.snapshot(app_id))}


def _stream(app_id: str, max_seconds: float) -> Iterator[str]:
    sub = app_bus.subscribe(app_id)
    started = time.monotonic()
    try:
        users = presence.public_view(presence.snapshot(app_id))
        yield sse_frame("hello", {"app_id": app_id})
        yield sse_frame("presence", {"users": users})
        last_sent = time.monotonic()
        last_refresh = last_sent
        while time.monotonic() - started < max_seconds:
            msg = sub.get(timeout=2.0)
            now = time.monotonic()
            if msg is not None:
                yield sse_frame(str(msg.get("event", "message")), msg.get("data", {}))
                last_sent = now
            if now - last_refresh >= PRESENCE_REFRESH_SECONDS:
                last_refresh = now
                fresh = presence.public_view(presence.snapshot(app_id))
                if fresh != users:  # 오래 연락이 없는 사람이 빠진 경우
                    users = fresh
                    yield sse_frame("presence", {"users": users})
                    last_sent = now
            if now - last_sent >= KEEPALIVE_SECONDS:
                yield ": keep-alive\n\n"
                last_sent = now
    finally:
        sub.close()


@router.get("/apps/{app_id}/presence/stream")
def presence_stream(
    app_id: str,
    ctx: AppViewers,
    max_seconds: Annotated[float, Query(ge=0.5, le=STREAM_MAX_SECONDS)] = STREAM_MAX_SECONDS,
) -> StreamingResponse:
    """접속 표시·작업본 변경(draft_changed)·댓글 변경(comment_changed)을 한 줄기로 받는다(SSE)."""
    del ctx
    return sse_response(_stream(app_id, max_seconds))


# ---------------- 댓글 ----------------
class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    node_id: str | None = Field(default=None, max_length=64)
    x: float | None = Field(default=None, ge=-100000, le=100000)
    y: float | None = Field(default=None, ge=-100000, le=100000)
    parent_id: str | None = Field(default=None, max_length=36)
    mentions: list[str] = Field(default_factory=list, max_length=20)


class CommentEdit(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    mentions: list[str] | None = Field(default=None, max_length=20)


def _get_comment(ctx: Ctx, app_id: str, comment_id: str) -> CanvasComment:
    c = ctx.db.get(CanvasComment, comment_id)
    if c is None or c.app_id != app_id:
        raise not_found("댓글")
    return c


def _thread(ctx: Ctx, root_id: str) -> dict[str, Any]:
    """뿌리 댓글 하나와 그 답글들."""
    rows = list(
        ctx.db.scalars(
            select(CanvasComment).where(
                (CanvasComment.id == root_id) | (CanvasComment.parent_id == root_id)
            )
        )
    )
    return collab.comment_dicts(ctx.db, rows)[0]


def _announce(
    request: Request, app_id: str, action: str, c: CanvasComment, user_id: str | None
) -> None:
    app_bus.publish(
        app_id,
        "comment_changed",
        {
            "action": action,
            "comment_id": c.id,
            "node_id": c.node_id,
            "user_id": user_id,
            "client_id": _client_id(request),
        },
    )


@router.get("/apps/{app_id}/comments")
def list_comments(
    app_id: str,
    ctx: AppViewers,
    status: Literal["open", "resolved", "all"] = "all",
    node_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[dict[str, Any]]:
    rows = list(
        ctx.db.scalars(
            select(CanvasComment)
            .where(CanvasComment.app_id == app_id)
            .order_by(CanvasComment.created_at)
            .limit(MAX_COMMENTS_PER_APP)
        )
    )
    threads = collab.comment_dicts(ctx.db, rows)
    if node_id is not None:
        threads = [t for t in threads if t["node_id"] == node_id]
    if status == "open":
        threads = [t for t in threads if not t["resolved"]]
    elif status == "resolved":
        threads = [t for t in threads if t["resolved"]]
    return threads


@router.post("/apps/{app_id}/comments", status_code=201)
def create_comment(
    app_id: str, body: CommentIn, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    text = body.body.strip()
    if not text:
        raise AppError(422, "댓글 내용이 비어 있어요.", "하고 싶은 말을 적은 뒤 보내세요.")
    count = len(
        list(ctx.db.scalars(select(CanvasComment.id).where(CanvasComment.app_id == app_id)))
    )
    if count >= MAX_COMMENTS_PER_APP:
        raise AppError(
            422,
            "이 앱의 댓글이 너무 많아요.",
            "해결된 댓글을 지운 뒤 다시 남겨 주세요.",
        )
    node_id, x, y = body.node_id, body.x, body.y
    if body.parent_id:
        parent = _get_comment(ctx, app_id, body.parent_id)
        if parent.parent_id is not None:
            raise AppError(
                422, "답글에는 다시 답글을 달 수 없어요.", "맨 위 댓글에 답글을 달아 주세요."
            )
        node_id, x, y = parent.node_id, parent.x, parent.y
    mentions = collab.valid_mentions(ctx.db, ctx.workspace_id, body.mentions)
    c = CanvasComment(
        app_id=app_id,
        node_id=node_id,
        x=x,
        y=y,
        parent_id=body.parent_id,
        body=text,
        mentions=mentions,
        created_by=ctx.user.id,
    )
    ctx.db.add(c)
    ctx.db.flush()
    collab.notify_mentions(
        ctx.db,
        app=app,
        comment=c,
        author=ctx.user,
        new_ids=mentions,
        link=f"{public_origin(request)}/apps/{app_id}/builder",
    )
    ctx.db.commit()
    _announce(request, app_id, "create", c, ctx.user.id)
    return _thread(ctx, c.parent_id or c.id)


@router.patch("/apps/{app_id}/comments/{comment_id}")
def edit_comment(
    app_id: str, comment_id: str, body: CommentEdit, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    c = _get_comment(ctx, app_id, comment_id)
    if c.created_by != ctx.user.id:
        raise AppError(
            403, "내가 쓴 댓글만 고칠 수 있어요.", "다른 사람의 댓글은 답글로 이야기해 주세요."
        )
    c.body = body.body.strip()
    if not c.body:
        raise AppError(422, "댓글 내용이 비어 있어요.", "내용을 적거나 댓글을 지워 주세요.")
    new_mentions: list[str] = []
    if body.mentions is not None:
        mentions = collab.valid_mentions(ctx.db, ctx.workspace_id, body.mentions)
        new_mentions = [m for m in mentions if m not in (c.mentions or [])]
        c.mentions = mentions
    c.edited_at = _now()
    if new_mentions:
        app = app_svc.get_app(ctx.db, app_id)
        collab.notify_mentions(
            ctx.db,
            app=app,
            comment=c,
            author=ctx.user,
            new_ids=new_mentions,
            link=f"{public_origin(request)}/apps/{app_id}/builder",
        )
    ctx.db.commit()
    _announce(request, app_id, "edit", c, ctx.user.id)
    return _thread(ctx, c.parent_id or c.id)


@router.delete("/apps/{app_id}/comments/{comment_id}", status_code=204)
def delete_comment(app_id: str, comment_id: str, request: Request, ctx: AppBuilders) -> Response:
    c = _get_comment(ctx, app_id, comment_id)
    if c.created_by != ctx.user.id and ctx.role not in ("owner", "admin"):
        raise AppError(
            403,
            "내가 쓴 댓글만 지울 수 있어요.",
            "다른 사람의 댓글은 관리자에게 지워 달라고 요청하세요.",
        )
    node_id = c.node_id
    for r in ctx.db.scalars(select(CanvasComment).where(CanvasComment.parent_id == c.id)):
        ctx.db.delete(r)
    ctx.db.delete(c)
    ctx.db.commit()
    app_bus.publish(
        app_id,
        "comment_changed",
        {
            "action": "delete",
            "comment_id": comment_id,
            "node_id": node_id,
            "user_id": ctx.user.id,
            "client_id": _client_id(request),
        },
    )
    return Response(status_code=204)


def _set_resolved(
    app_id: str, comment_id: str, value: bool, request: Request, ctx: Ctx
) -> dict[str, Any]:
    c = _get_comment(ctx, app_id, comment_id)
    if c.parent_id is not None:
        raise AppError(
            422, "답글은 따로 해결할 수 없어요.", "맨 위 댓글에서 해결 처리를 해 주세요."
        )
    c.resolved = value
    c.resolved_by = ctx.user.id if value else None
    ctx.db.commit()
    _announce(request, app_id, "resolve" if value else "reopen", c, ctx.user.id)
    return _thread(ctx, c.id)


@router.post("/apps/{app_id}/comments/{comment_id}/resolve")
def resolve_comment(
    app_id: str, comment_id: str, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    return _set_resolved(app_id, comment_id, True, request, ctx)


@router.post("/apps/{app_id}/comments/{comment_id}/reopen")
def reopen_comment(
    app_id: str, comment_id: str, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    return _set_resolved(app_id, comment_id, False, request, ctx)


@router.get("/apps/{app_id}/collaborators")
def collaborators(app_id: str, ctx: AppViewers) -> list[dict[str, Any]]:
    """@멘션 후보: 이 워크스페이스에서 빌더를 열 수 있는 사람(이름·역할만, 이메일은 보내지 않는다)."""
    rows = ctx.db.execute(
        select(User.id, User.name, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == ctx.workspace_id, Membership.role.in_(VIEW_RUNS))
        .order_by(User.name)
    ).all()
    return [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]
