"""프로젝트: 워크스페이스 안에서 앱·지식베이스를 묶어 관리(개인 프로젝트는 비공개)."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.core.audit import audit
from api.core.errors import AppError, forbidden, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, Ctx, require_role
from api.models import App, KnowledgeBase, Membership, Project, ProjectMember, User
from api.services import projects as svc

router = APIRouter(tags=["projects"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
ProjectMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER, via="project"))]
ProjectBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="project"))]

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
