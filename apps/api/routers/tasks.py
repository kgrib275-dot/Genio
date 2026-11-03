"""작업함: 흐름이 사람에게 맡긴 일(승인·질문·배정)을 보고 처리한다(기능 정의서 S7).

- 로그인한 멤버: /workspaces/{ws}/tasks...
- 링크(이메일·슬랙으로 받은 /t/{token}): /public/tasks/{token} — 토큰이 곧 권한
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.errors import AppError, forbidden, not_found
from api.deps import ANY_MEMBER, Ctx, DbDep, require_role
from api.models import App, HumanTask, Run
from api.routers.common import client_ip
from api.services import tasks as svc
from api.services.projects import hidden_project_ids
from api.services.queue import enqueue_run

router = APIRouter(tags=["tasks"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]


def _hidden_apps(ctx: Ctx, ws: str) -> set[str]:
    hidden = hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    if not hidden:
        return set()
    return set(
        ctx.db.scalars(select(App.id).where(App.workspace_id == ws, App.project_id.in_(hidden)))
    )


def _get(ctx: Ctx, ws: str, task_id: str) -> HumanTask:
    task = ctx.db.get(HumanTask, task_id)
    if task is None or task.workspace_id != ws or task.app_id in _hidden_apps(ctx, ws):
        raise not_found("할 일")
    return task


def _mine_filter(ctx: Ctx) -> Any:
    return or_(
        HumanTask.assignee_user_id == ctx.user.id,
        HumanTask.assignee_role == ctx.role,
        (HumanTask.assignee_user_id.is_(None) & HumanTask.assignee_role.is_(None)),
    )


@router.get("/workspaces/{ws}/tasks")
def list_tasks(
    ws: str,
    ctx: Members,
    status: Literal["open", "done", "cancelled", "all"] = "open",
    mine: bool = False,
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[dict[str, Any]]:
    q = (
        select(HumanTask, App.name)
        .join(App, App.id == HumanTask.app_id)
        .where(HumanTask.workspace_id == ws)
    )
    if status != "all":
        q = q.where(HumanTask.status == status)
    if mine:
        q = q.where(_mine_filter(ctx))
    hidden = _hidden_apps(ctx, ws)
    rows = ctx.db.execute(q.order_by(HumanTask.created_at.desc()).limit(limit)).all()
    out = []
    for t, app_name in rows:
        if t.app_id in hidden:
            continue
        run = ctx.db.get(Run, t.run_id) if t.run_id else None
        d = svc.task_dict(t, app_name)
        d["can_act"] = t.status == "open" and svc.can_act(t, run, ctx.user.id, ctx.role)
        out.append(d)
    return out


@router.get("/workspaces/{ws}/tasks/count")
def open_count(ws: str, ctx: Members) -> dict[str, int]:
    """메뉴 배지용: 내가 처리할 수 있는 열린 일 수."""
    hidden = _hidden_apps(ctx, ws)
    rows = ctx.db.scalars(
        select(HumanTask).where(
            HumanTask.workspace_id == ws, HumanTask.status == "open", _mine_filter(ctx)
        )
    )
    n = 0
    for t in rows:
        if t.app_id in hidden:
            continue
        run = ctx.db.get(Run, t.run_id) if t.run_id else None
        if svc.can_act(t, run, ctx.user.id, ctx.role):
            n += 1
    return {"open": n}


@router.get("/workspaces/{ws}/tasks/{task_id}")
def get_task(ws: str, task_id: str, ctx: Members) -> dict[str, Any]:
    task = _get(ctx, ws, task_id)
    app = ctx.db.get(App, task.app_id)
    run = ctx.db.get(Run, task.run_id) if task.run_id else None
    d = svc.task_dict(task, app.name if app else "")
    d["can_act"] = task.status == "open" and svc.can_act(task, run, ctx.user.id, ctx.role)
    return d


class CompleteIn(BaseModel):
    approved: bool | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=1000)


@router.post("/workspaces/{ws}/tasks/{task_id}/complete")
def complete_task(ws: str, task_id: str, body: CompleteIn, ctx: Members) -> dict[str, Any]:
    task = _get(ctx, ws, task_id)
    run = ctx.db.get(Run, task.run_id) if task.run_id else None
    if not svc.can_act(task, run, ctx.user.id, ctx.role):
        raise forbidden()
    resumed = svc.complete(
        ctx.db,
        task,
        approved=body.approved,
        values=body.values,
        comment=body.comment,
        user=ctx.user,
        via="inbox",
    )
    if resumed is not None:
        enqueue_run(resumed.id)
    app = ctx.db.get(App, task.app_id)
    return svc.task_dict(task, app.name if app else "")


@router.post("/workspaces/{ws}/tasks/{task_id}/cancel")
def cancel_task(ws: str, task_id: str, ctx: Members) -> dict[str, Any]:
    task = _get(ctx, ws, task_id)
    if ctx.role not in ("owner", "admin", "builder"):
        raise forbidden()
    svc.cancel(ctx.db, task, ctx.user)
    app = ctx.db.get(App, task.app_id)
    return svc.task_dict(task, app.name if app else "")


# ---------------- 링크(로그인 없이) ----------------
def _by_token(db: Session, token: str) -> HumanTask:
    task = db.scalar(select(HumanTask).where(HumanTask.token == token[:64]))
    if task is None:
        raise AppError(404, "요청을 찾을 수 없어요.", "받은 링크가 맞는지 확인하세요.")
    return task


def _limited(request: Request) -> None:
    if not ratelimit.allow(f"task-link:{client_ip(request)}", 60):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")


@router.get("/public/tasks/{token}")
def public_task(token: str, request: Request, db: DbDep) -> dict[str, Any]:
    _limited(request)
    task = _by_token(db, token)
    app = db.get(App, task.app_id)
    d = svc.task_dict(task, app.name if app else "")
    # 링크 화면에는 담당자 id 같은 내부 값을 보이지 않는다
    for k in ("assignee_user_id", "run_id", "node_id", "app_id"):
        d.pop(k, None)
    return d


@router.post("/public/tasks/{token}")
def public_complete(token: str, body: CompleteIn, request: Request, db: DbDep) -> dict[str, Any]:
    _limited(request)
    task = _by_token(db, token)
    resumed = svc.complete(
        db,
        task,
        approved=body.approved,
        values=body.values,
        comment=body.comment,
        user=None,
        via="link",
    )
    if resumed is not None:
        enqueue_run(resumed.id)
    app = db.get(App, task.app_id)
    d = svc.task_dict(task, app.name if app else "")
    for k in ("assignee_user_id", "run_id", "node_id", "app_id"):
        d.pop(k, None)
    return d
