"""v0.6 처음 쓰는 사람 안내: 시작 체크리스트 진행 상태(실제 데이터로 판단)와 의견·문의.

- 체크리스트 상태는 워크스페이스 데이터를 세어서 판단한다(누가 했든 이 워크스페이스 기준).
- 의견·문의는 새 표를 만들지 않고 활동 기록(audit_logs, action "feedback.send")에 남긴다.
  보내기는 멤버 누구나, 목록은 소유자·관리자만(활동 기록 화면 '의견' 필터와 같은 데이터).
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError
from api.deps import ANY_MEMBER, MANAGE_MEMBERS, Ctx, require_role
from api.models import (
    App,
    AuditLog,
    Deployment,
    Invitation,
    LlmProvider,
    Membership,
    Run,
    User,
    WorkflowVersion,
    Workspace,
)

router = APIRouter(tags=["onboarding"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]

FEEDBACK_ACTION = "feedback.send"


def _count(ctx: Ctx, stmt: Any) -> int:
    return int(ctx.db.scalar(stmt) or 0)


@router.get("/workspaces/{ws}/onboarding")
def onboarding_status(ws: str, ctx: Members) -> dict[str, Any]:
    """시작 체크리스트 각 항목을 실제 데이터로 판단한다(True면 끝남)."""
    apps = select(App.id).where(App.workspace_id == ws)
    workspace = ctx.db.get(Workspace, ws)
    members = _count(
        ctx, select(func.count()).select_from(Membership).where(Membership.workspace_id == ws)
    )
    invites = _count(
        ctx, select(func.count()).select_from(Invitation).where(Invitation.workspace_id == ws)
    )
    return {
        "ai_connected": _count(
            ctx, select(func.count()).select_from(LlmProvider).where(LlmProvider.workspace_id == ws)
        )
        > 0,
        "samples_installed": bool(
            ((workspace.settings if workspace else None) or {}).get("samples_version")
        ),
        "app_created": _count(
            ctx, select(func.count()).select_from(App).where(App.workspace_id == ws)
        )
        > 0,
        "test_run": _count(ctx, select(func.count()).select_from(Run).where(Run.app_id.in_(apps)))
        > 0,
        "version_saved": _count(
            ctx,
            select(func.count())
            .select_from(WorkflowVersion)
            .where(WorkflowVersion.app_id.in_(apps)),
        )
        > 0,
        "deployed": _count(
            ctx, select(func.count()).select_from(Deployment).where(Deployment.app_id.in_(apps))
        )
        > 0,
        "team_invited": members > 1 or invites > 0,
    }


class FeedbackIn(BaseModel):
    kind: Literal["question", "bug", "idea", "other"] = "question"
    message: str = Field(min_length=2, max_length=3000)
    page: str = Field(default="", max_length=300)


@router.post("/workspaces/{ws}/feedback", status_code=201)
def send_feedback(ws: str, body: FeedbackIn, ctx: Members) -> dict[str, Any]:
    if not ratelimit.allow(f"feedback:{ctx.user.id}", limit=10, window=600):
        raise AppError(
            429,
            "의견을 너무 자주 보냈어요.",
            "10분 뒤에 다시 보내 주세요. 급하면 관리자에게 직접 알려 주세요.",
        )
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action=FEEDBACK_ACTION,
        target_type="feedback",
        meta={"kind": body.kind, "message": body.message.strip(), "page": body.page},
    )
    ctx.db.commit()
    return {"ok": True}


@router.get("/workspaces/{ws}/feedback")
def list_feedback(
    ws: str, ctx: Managers, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(AuditLog, User.email, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.workspace_id == ws, AuditLog.action == FEEDBACK_ACTION)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": a.id,
            "user_email": email,
            "user_name": name,
            "kind": (a.meta or {}).get("kind", "other"),
            "message": (a.meta or {}).get("message", ""),
            "page": (a.meta or {}).get("page", ""),
            "created_at": a.created_at,
        }
        for a, email, name in rows
    ]
