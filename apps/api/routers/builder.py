"""빌더 챗: 세션과 메시지(SSE)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.builder import checkpoint
from api.builder.agent import message_dict, run_turn
from api.builder.metrics import workspace_metrics
from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, MANAGE_MEMBERS, Ctx, require_role
from api.models import BuilderMessage, BuilderSession
from api.routers.common import sse_frame, sse_response

router = APIRouter(tags=["builder"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
SessionBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="session"))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]


@router.get("/workspaces/{ws}/builder/metrics")
def builder_metrics(ws: str, ctx: Managers) -> dict[str, Any]:
    """대화형 빌더 지표(기능 정의서 S1): 첫 요청→검증 통과 시간, 수정 대화 수, 캔버스 직접 편집 비율."""
    return workspace_metrics(ctx.db, ws)


def _session(s: BuilderSession) -> dict[str, Any]:
    return {"id": s.id, "app_id": s.app_id, "user_id": s.user_id, "created_at": s.created_at}


@router.get("/apps/{app_id}/builder/sessions")
def list_sessions(app_id: str, ctx: AppBuilders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(BuilderSession)
        .where(BuilderSession.app_id == app_id)
        .order_by(BuilderSession.created_at.desc())
    )
    return [_session(s) for s in rows]


@router.post("/apps/{app_id}/builder/sessions")
def create_session(app_id: str, ctx: AppBuilders) -> dict[str, Any]:
    s = BuilderSession(app_id=app_id, user_id=ctx.user.id)
    ctx.db.add(s)
    ctx.db.commit()
    return _session(s)


@router.get("/builder/sessions/{session_id}/messages")
def list_messages(session_id: str, ctx: SessionBuilders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(BuilderMessage)
        .where(BuilderMessage.session_id == session_id)
        .order_by(BuilderMessage.created_at)
    )
    return [message_dict(m) for m in rows]


class BuilderEvent(BaseModel):
    type: Literal["installed"]
    item_key: str


class MessageIn(BaseModel):
    content: str = Field(default="", max_length=4000)
    event: BuilderEvent | None = None
    plan_only: bool = False  # 먼저 계획만 보여 주기(흐름을 바꾸지 않음)


@router.post("/builder/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn, ctx: SessionBuilders) -> StreamingResponse:
    user_id = ctx.user.id
    # 같은 대화에서 앞 요청에 아직 답하는 중이면 막는다(두 요청이 같은 흐름을 동시에 고치지 않게).
    # 서버가 멈춰 답 없이 끝난 요청은 3분이 지나면 새로 보낼 수 있다.
    last = ctx.db.scalar(
        select(BuilderMessage)
        .where(BuilderMessage.session_id == session_id)
        .order_by(BuilderMessage.created_at.desc())
        .limit(1)
    )
    if last is not None and last.role == "user":
        made = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=UTC)
        if (datetime.now(UTC) - made).total_seconds() < 180:
            raise AppError(
                409,
                "앞 요청에 아직 답하는 중이에요.",
                "답이 끝난 뒤에 다음 말을 보내 주세요.",
            )

    def frames() -> Iterator[str]:
        event = body.event.model_dump() if body.event else None
        for name, data in run_turn(session_id, user_id, body.content, event, body.plan_only):
            yield sse_frame(name, data)

    return sse_response(frames())


class RevertIn(BaseModel):
    force: bool = False


@router.post("/builder/sessions/{session_id}/messages/{message_id}/revert")
def revert_message(
    session_id: str, message_id: str, body: RevertIn, ctx: SessionBuilders
) -> dict[str, Any]:
    """빌더가 한 차례에 바꾼 흐름을 바꾸기 전 모습으로 되돌린다."""
    out = checkpoint.revert_turn(ctx.db, session_id, message_id, force=body.force)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="builder.revert",
        target_type="builder_message",
        target_id=message_id,
        meta={"had_later_changes": out["had_later_changes"]},
    )
    ctx.db.commit()
    return out
