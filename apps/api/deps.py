"""인증과 역할 검사. 모든 라우터는 require_role 의존성으로 설계서 §3-1 권한표를 강제한다."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError, forbidden, not_found
from api.core.security import decode_token
from api.db import get_db
from api.models import (
    Annotation,
    App,
    AppApiKey,
    BuilderSession,
    Chunk,
    Conversation,
    Deployment,
    Document,
    KnowledgeBase,
    Membership,
    Run,
    User,
)

Role = Literal["owner", "admin", "builder", "operator", "member"]
ROLES: tuple[Role, ...] = ("owner", "admin", "builder", "operator", "member")

# 설계서 §3-1 역할 권한표
MANAGE_MEMBERS: tuple[Role, ...] = ("owner", "admin")
MANAGE_SECRETS: tuple[Role, ...] = ("owner", "admin")
MANAGE_MARKET: tuple[Role, ...] = ("owner", "admin")
EDIT_APPS: tuple[Role, ...] = ("owner", "admin", "builder")
DEPLOY_APPS: tuple[Role, ...] = ("owner", "admin", "builder")
VIEW_RUNS: tuple[Role, ...] = ("owner", "admin", "builder", "operator")
ANY_MEMBER: tuple[Role, ...] = ROLES

DbDep = Annotated[Session, Depends(get_db)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # SSE 등 헤더를 못 붙이는 경우를 위한 보조 경로
    return request.query_params.get("access_token")


def get_optional_user(request: Request, db: DbDep) -> User | None:
    token = _bearer(request)
    if not token:
        return None
    user_id = decode_token(token, "access")
    if not user_id:
        return None
    return db.get(User, user_id)


def get_current_user(request: Request, db: DbDep) -> User:
    user = get_optional_user(request, db)
    if user is None:
        raise AppError(401, "로그인이 필요해요.", "다시 로그인한 뒤 시도하세요.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class Ctx:
    user: User
    workspace_id: str
    role: Role
    db: Session


Via = Literal[
    "ws",
    "app",
    "run",
    "session",
    "kb",
    "deployment",
    "document",
    "conversation",
    "annotation",
    "api_key",
    "chunk",
]


def _workspace_of(db: Session, via: Via, key: str) -> str:
    if via == "ws":
        return key
    if via == "app":
        app = db.get(App, key)
        if app is None:
            raise not_found("앱")
        return app.workspace_id
    if via == "run":
        run = db.get(Run, key)
        if run is None:
            raise not_found("실행 기록")
        return _workspace_of(db, "app", run.app_id)
    if via == "session":
        sess = db.get(BuilderSession, key)
        if sess is None:
            raise not_found("빌더 대화")
        return _workspace_of(db, "app", sess.app_id)
    if via == "kb":
        kb = db.get(KnowledgeBase, key)
        if kb is None:
            raise not_found("지식베이스")
        return kb.workspace_id
    if via == "document":
        doc = db.get(Document, key)
        if doc is None:
            raise not_found("문서")
        return _workspace_of(db, "kb", doc.kb_id)
    if via == "conversation":
        conv = db.get(Conversation, key)
        if conv is None:
            raise not_found("대화")
        return _workspace_of(db, "app", conv.app_id)
    if via == "annotation":
        ann = db.get(Annotation, key)
        if ann is None:
            raise not_found("주석")
        return _workspace_of(db, "app", ann.app_id)
    if via == "api_key":
        k = db.get(AppApiKey, key)
        if k is None:
            raise not_found("API 키")
        return _workspace_of(db, "app", k.app_id)
    if via == "chunk":
        ch = db.get(Chunk, key)
        if ch is None:
            raise not_found("조각")
        return _workspace_of(db, "kb", ch.kb_id)
    dep = db.get(Deployment, key)
    if dep is None:
        raise not_found("배포")
    return _workspace_of(db, "app", dep.app_id)


_PARAM = {
    "ws": "ws",
    "app": "app_id",
    "run": "run_id",
    "session": "session_id",
    "kb": "kb_id",
    "deployment": "deployment_id",
    "document": "document_id",
    "conversation": "conversation_id",
    "annotation": "annotation_id",
    "api_key": "key_id",
    "chunk": "chunk_id",
}


def membership_role(db: Session, user_id: str, workspace_id: str) -> Role | None:
    m = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    return m.role if m else None  # type: ignore[return-value]


def require_role(roles: tuple[Role, ...], via: Via = "ws") -> Callable[..., Ctx]:
    """경로 파라미터로 워크스페이스를 찾고, 현재 사용자의 역할이 roles에 있는지 확인한다."""

    def dep(request: Request, user: CurrentUser, db: DbDep) -> Ctx:
        key = request.path_params.get(_PARAM[via])
        if not key:
            raise not_found("대상")
        workspace_id = _workspace_of(db, via, str(key))
        role = membership_role(db, user.id, workspace_id)
        if role is None:
            # 다른 워크스페이스의 존재 여부를 드러내지 않는다
            raise not_found("대상")
        if role not in roles:
            raise forbidden()
        return Ctx(user=user, workspace_id=workspace_id, role=role, db=db)

    return dep
