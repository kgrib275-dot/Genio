"""홈의 '지금 할 일': 실패한 실행과 싫어요 받은 답이 있는 앱을 한곳에 모아 알려 준다(제작자 이상)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.deps import EDIT_APPS, Ctx, require_role
from api.models import App, Conversation, Message, Run
from api.services.impact import NOT_COUNTED_TRIGGERS

router = APIRouter(tags=["workspaces"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


@router.get("/workspaces/{ws}/attention")
def attention(ws: str, ctx: WsBuilders) -> dict[str, Any]:
    now = datetime.now(UTC)
    failed = ctx.db.execute(
        select(App.id, App.name, func.count(Run.id))
        .join(Run, Run.app_id == App.id)
        .where(
            App.workspace_id == ws,
            Run.status == "failed",
            Run.created_at >= now - timedelta(hours=24),
            Run.trigger.not_in(NOT_COUNTED_TRIGGERS),
        )
        .group_by(App.id, App.name)
        .order_by(func.count(Run.id).desc())
        .limit(5)
    ).all()
    disliked = ctx.db.execute(
        select(App.id, App.name, func.count(Message.id))
        .join(Conversation, Conversation.app_id == App.id)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(
            App.workspace_id == ws,
            Message.role == "assistant",
            Message.feedback == "dislike",
            Message.annotation_id.is_(None),
            Message.created_at >= now - timedelta(days=30),
        )
        .group_by(App.id, App.name)
        .order_by(func.count(Message.id).desc())
        .limit(5)
    ).all()
    return {
        "failed": [{"app_id": a, "app_name": n, "count": int(c)} for a, n, c in failed],
        "disliked": [{"app_id": a, "app_name": n, "count": int(c)} for a, n, c in disliked],
    }
