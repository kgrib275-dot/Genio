"""홈의 '지금 할 일': 실패한 실행과 싫어요 받은 답이 있는 앱을 한곳에 모아 알려 준다(제작자 이상)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from api.deps import EDIT_APPS, MANAGE_MEMBERS, Ctx, require_role
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


@router.get("/workspaces/{ws}/activation")
def activation(
    ws: str, ctx: Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]
) -> dict[str, Any]:
    """첫 사용 성공률: 멤버가 어디까지 해 봤는지(가입 → 앱 만들기 → 써 보기 → 공유 → 다른 사람이 씀)."""
    from api.models import Deployment, Membership

    db = ctx.db
    members = set(db.scalars(select(Membership.user_id).where(Membership.workspace_id == ws)))
    apps = list(db.execute(select(App.id, App.created_by).where(App.workspace_id == ws)).all())
    app_ids = [a for a, _ in apps]
    owner_of = {a: u for a, u in apps if u}
    made = {u for u in owner_of.values() if u in members}
    tested: set[str] = set()
    shared: set[str] = set()
    used_apps = 0
    if app_ids:
        for uid in db.scalars(
            select(Run.created_by)
            .where(Run.app_id.in_(app_ids), Run.trigger.in_(("test", "preview")))
            .distinct()
        ):
            if uid in members:
                tested.add(uid)
        for app_id in db.scalars(
            select(Deployment.app_id).where(Deployment.app_id.in_(app_ids)).distinct()
        ):
            u = owner_of.get(app_id)
            if u in members:
                shared.add(u)
        used_apps = int(
            db.scalar(
                select(func.count(func.distinct(Conversation.app_id))).where(
                    Conversation.app_id.in_(app_ids)
                )
            )
            or 0
        )
    steps = [
        ("가입한 멤버", len(members)),
        ("앱을 만든 멤버", len(made)),
        ("직접 써 본 멤버", len(tested)),
        ("공유까지 한 멤버", len(shared)),
        ("다른 사람이 쓴 앱", used_apps),
    ]
    top = steps[0][1] or 1
    return {
        "steps": [
            {"label": n, "count": c, "rate": round(c / top, 3) if i < 4 else None}
            for i, (n, c) in enumerate(steps)
        ],
        "apps": len(app_ids),
    }
