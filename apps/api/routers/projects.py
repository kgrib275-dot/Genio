"""프로젝트: 워크스페이스 안에서 앱·지식베이스를 묶어 관리(개인 프로젝트는 비공개)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.core.audit import audit
from api.core.errors import AppError, forbidden, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import (
    App,
    Conversation,
    Document,
    KnowledgeBase,
    Membership,
    Project,
    ProjectMember,
    Run,
    User,
)
from api.services import projects as svc

router = APIRouter(tags=["projects"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
ProjectMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER, via="project"))]
ProjectBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="project"))]
Viewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]

Color = Literal["indigo", "sky", "emerald", "amber", "rose", "violet", "slate"]


def project_dict(ctx: Ctx, p: Project) -> dict[str, Any]:
    apps = ctx.db.scalar(select(func.count()).select_from(App).where(App.project_id == p.id)) or 0
    kbs = (
        ctx.db.scalar(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.project_id == p.id)
        )
        or 0
    )
    members = ctx.db.execute(
        select(User.id, User.name, User.email)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == p.id)
    ).all()
    owner = ctx.db.get(User, p.created_by) if p.created_by else None
    return {
        "id": p.id,
        "workspace_id": p.workspace_id,
        "name": p.name,
        "description": p.description,
        "color": p.color,
        "visibility": p.visibility,
        "created_by": p.created_by,
        "created_by_name": owner.name if owner else "",
        "created_at": p.created_at,
        "app_count": apps,
        "knowledge_base_count": kbs,
        "members": [{"user_id": m[0], "name": m[1], "email": m[2]} for m in members],
        "can_manage": svc.can_manage(p, ctx.user.id, ctx.role),
    }


@router.get("/workspaces/{ws}/projects")
def list_projects(ws: str, ctx: Members) -> list[dict[str, Any]]:
    hidden = svc.hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    rows = ctx.db.scalars(
        select(Project).where(Project.workspace_id == ws).order_by(Project.created_at)
    )
    return [project_dict(ctx, p) for p in rows if p.id not in hidden]


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    color: Color = "indigo"
    visibility: Literal["workspace", "private"] = "workspace"


@router.post("/workspaces/{ws}/projects", status_code=201)
def create_project(ws: str, body: ProjectIn, ctx: Builders) -> dict[str, Any]:
    p = Project(workspace_id=ws, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="project.create",
        target_type="project",
        target_id=p.id,
        meta={"name": p.name, "visibility": p.visibility},
    )
    ctx.db.commit()
    return project_dict(ctx, p)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    color: Color | None = None
    visibility: Literal["workspace", "private"] | None = None


def _manageable(ctx: Ctx, project_id: str) -> Project:
    p = ctx.db.get(Project, project_id)
    if p is None:
        raise not_found("프로젝트")
    if not svc.can_manage(p, ctx.user.id, ctx.role):
        raise AppError(
            403,
            "이 프로젝트는 만든 사람이나 관리자만 고칠 수 있어요.",
            "프로젝트를 만든 사람에게 요청하세요.",
        )
    return p


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, ctx: ProjectBuilders) -> dict[str, Any]:
    p = _manageable(ctx, project_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    audit(
        ctx.db,
        workspace_id=p.workspace_id,
        user_id=ctx.user.id,
        action="project.update",
        target_type="project",
        target_id=p.id,
        meta=body.model_dump(exclude_none=True),
    )
    ctx.db.commit()
    return project_dict(ctx, p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, ctx: ProjectBuilders) -> Response:
    p = _manageable(ctx, project_id)
    # 앱·지식베이스는 지우지 않고 '프로젝트 없음(공용)'으로 옮긴다
    for app in ctx.db.scalars(select(App).where(App.project_id == p.id)):
        app.project_id = None
    for kb in ctx.db.scalars(select(KnowledgeBase).where(KnowledgeBase.project_id == p.id)):
        kb.project_id = None
    ctx.db.delete(p)
    audit(
        ctx.db,
        workspace_id=p.workspace_id,
        user_id=ctx.user.id,
        action="project.delete",
        target_type="project",
        target_id=project_id,
        meta={"name": p.name},
    )
    ctx.db.commit()
    return Response(status_code=204)


class MembersIn(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=200)


@router.put("/projects/{project_id}/members")
def set_members(project_id: str, body: MembersIn, ctx: ProjectBuilders) -> dict[str, Any]:
    p = _manageable(ctx, project_id)
    valid = set(
        ctx.db.scalars(select(Membership.user_id).where(Membership.workspace_id == p.workspace_id))
    )
    bad = [u for u in body.user_ids if u not in valid]
    if bad:
        raise AppError(422, "워크스페이스 멤버가 아닌 사람이 있어요.", "멤버 목록에서 고르세요.")
    for m in ctx.db.scalars(select(ProjectMember).where(ProjectMember.project_id == p.id)):
        ctx.db.delete(m)
    ctx.db.flush()
    for uid in dict.fromkeys(body.user_ids):
        ctx.db.add(ProjectMember(project_id=p.id, user_id=uid))
    audit(
        ctx.db,
        workspace_id=p.workspace_id,
        user_id=ctx.user.id,
        action="project.members",
        target_type="project",
        target_id=p.id,
        meta={"count": len(body.user_ids)},
    )
    ctx.db.commit()
    return project_dict(ctx, p)


def check_project_target(ctx: Ctx, workspace_id: str, project_id: str | None) -> None:
    """앱·지식베이스를 옮겨 넣을 프로젝트가 이 워크스페이스에 있고, 사용자가 볼 수 있는지 확인."""
    if not project_id:
        return
    p = ctx.db.get(Project, project_id)
    if p is None or p.workspace_id != workspace_id:
        raise not_found("프로젝트")
    if not svc.can_access(ctx.db, p, ctx.user.id, ctx.role):
        raise forbidden()


# ---------------- 프로젝트 현황판 ----------------
def _day(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).date().isoformat()


def _empty(keys: list[str]) -> dict[str, Any]:
    return {
        "apps": 0,
        "published_apps": 0,
        "knowledge_bases": 0,
        "documents": 0,
        "runs": 0,
        "succeeded": 0,
        "failed": 0,
        "waiting_approval": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": Decimal(0),
        "conversations": 0,
        "last_activity_at": None,
        "series": {k: 0 for k in keys},
    }


@router.get("/workspaces/{ws}/projects/overview")
def projects_overview(ws: str, ctx: Viewers, days: int = 30) -> dict[str, Any]:
    days = max(1, min(days, 90))
    db = ctx.db
    since = (datetime.now(UTC) - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    keys = [(since + timedelta(days=i)).date().isoformat() for i in range(days)]
    hidden = svc.hidden_project_ids(db, ws, ctx.user.id, ctx.role)
    projects = [
        p
        for p in db.scalars(
            select(Project).where(Project.workspace_id == ws).order_by(Project.created_at)
        )
        if p.id not in hidden
    ]
    stats: dict[str | None, dict[str, Any]] = {p.id: _empty(keys) for p in projects}
    stats[None] = _empty(keys)  # 프로젝트 없음(공용)

    def bump_last(st: dict[str, Any], dt: datetime | None) -> None:
        if dt is None:
            return
        dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        if st["last_activity_at"] is None or dt > st["last_activity_at"]:
            st["last_activity_at"] = dt

    apps = [
        a
        for a in db.scalars(select(App).where(App.workspace_id == ws))
        if a.project_id not in hidden
    ]
    app_project: dict[str, str | None] = {}
    for a in apps:
        st = stats.get(a.project_id) or stats[None]
        app_project[a.id] = a.project_id if a.project_id in stats else None
        st["apps"] += 1
        st["published_apps"] += 1 if a.status == "published" else 0
        bump_last(st, a.updated_at)
    kbs = [
        k
        for k in db.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == ws))
        if k.project_id not in hidden
    ]
    kb_project = {k.id: (k.project_id if k.project_id in stats else None) for k in kbs}
    for k in kbs:
        stats[kb_project[k.id]]["knowledge_bases"] += 1
    if kb_project:
        for kb_id, n in db.execute(
            select(Document.kb_id, func.count(Document.id))
            .where(Document.kb_id.in_(list(kb_project)))
            .group_by(Document.kb_id)
        ).all():
            stats[kb_project[kb_id]]["documents"] += int(n)
    if app_project:
        for r in db.scalars(
            select(Run).where(Run.app_id.in_(list(app_project)), Run.created_at >= since)
        ):
            st = stats[app_project[r.app_id]]
            st["runs"] += 1
            if r.status in ("succeeded", "failed", "waiting_approval"):
                st[r.status] += 1
            u = r.token_usage or {}
            st["input_tokens"] += int(u.get("input_tokens", 0))
            st["output_tokens"] += int(u.get("output_tokens", 0))
            st["cost"] += Decimal(str(r.cost or 0))
            d = _day(r.created_at)
            if d in st["series"]:
                st["series"][d] += 1
            bump_last(st, r.created_at)
        for c in db.scalars(
            select(Conversation).where(
                Conversation.app_id.in_(list(app_project)), Conversation.created_at >= since
            )
        ):
            st = stats[app_project[c.app_id]]
            st["conversations"] += 1
            bump_last(st, c.created_at)

    def finish(st: dict[str, Any]) -> dict[str, Any]:
        done = st["succeeded"] + st["failed"]
        return {
            **{k: v for k, v in st.items() if k not in ("series", "cost")},
            "cost": float(st["cost"]),
            "success_rate": round(st["succeeded"] / done, 3) if done else None,
            "series": [{"date": k, "runs": st["series"][k]} for k in keys],
        }

    rows = [{"project": project_dict(ctx, p), **finish(stats[p.id])} for p in projects]
    unassigned = finish(stats[None])
    all_stats = [r for r in rows] + [unassigned]
    totals = {
        "projects": len(projects),
        "apps": sum(r["apps"] for r in all_stats),
        "published_apps": sum(r["published_apps"] for r in all_stats),
        "runs": sum(r["runs"] for r in all_stats),
        "succeeded": sum(r["succeeded"] for r in all_stats),
        "failed": sum(r["failed"] for r in all_stats),
        "waiting_approval": sum(r["waiting_approval"] for r in all_stats),
        "cost": round(sum(r["cost"] for r in all_stats), 6),
        "conversations": sum(r["conversations"] for r in all_stats),
    }
    done = totals["succeeded"] + totals["failed"]
    totals["success_rate"] = round(totals["succeeded"] / done, 3) if done else None
    return {"days": days, "totals": totals, "projects": rows, "unassigned": unassigned}
