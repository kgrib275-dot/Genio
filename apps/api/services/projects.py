"""프로젝트 접근 규칙.

- visibility="workspace": 워크스페이스의 모든 멤버가 본다(역할 권한은 그대로).
- visibility="private": 만든 사람, 프로젝트 멤버, 워크스페이스 소유자·관리자만 본다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Project, ProjectMember

ADMIN_ROLES = ("owner", "admin")


def can_access(db: Session, project: Project | None, user_id: str, role: str) -> bool:
    if project is None or project.visibility != "private":
        return True
    if role in ADMIN_ROLES or project.created_by == user_id:
        return True
    return (
        db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
            )
        )
        is not None
    )


def can_manage(project: Project, user_id: str, role: str) -> bool:
    return role in ADMIN_ROLES or project.created_by == user_id


def hidden_project_ids(db: Session, workspace_id: str, user_id: str, role: str) -> set[str]:
    """이 사용자가 볼 수 없는 비공개 프로젝트 id들."""
    if role in ADMIN_ROLES:
        return set()
    private = list(
        db.scalars(
            select(Project).where(
                Project.workspace_id == workspace_id, Project.visibility == "private"
            )
        )
    )
    if not private:
        return set()
    mine = set(
        db.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user_id,
                ProjectMember.project_id.in_([p.id for p in private]),
            )
        )
    )
    return {p.id for p in private if p.created_by != user_id and p.id not in mine}
