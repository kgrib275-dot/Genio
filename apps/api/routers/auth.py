"""인증·내 정보. 로그인 전 엔드포인트라 require_role 대신 공개(또는 로그인만 필요)다."""

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.core.security import create_tokens, decode_token, hash_password, verify_password
from api.deps import CurrentUser, DbDep
from api.models import Invitation, Membership, Organization, User, Workspace
from api.services.apps import slugify

router = APIRouter(tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    workspace_name: str | None = Field(default=None, max_length=100)


class LoginIn(BaseModel):
    # 로그인은 형식 검사 없이 받는다(가입 시점 규칙이 바뀌어도 기존 계정이 로그인할 수 있게)
    email: str = Field(min_length=3, max_length=320)
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class AcceptIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)


def create_workspace(db: Session, owner: User, name: str) -> Workspace:
    slug = slugify(re.sub(r"\s+", "-", name))
    org = Organization(name=name, slug=slug)
    db.add(org)
    db.flush()
    ws = Workspace(org_id=org.id, name=name, slug=slug, settings={"locale": "ko"})
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=owner.id, workspace_id=ws.id, role="owner"))
    return ws


@router.post("/auth/signup")
def signup(body: SignupIn, db: DbDep) -> dict[str, str]:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError(409, "이미 가입된 이메일이에요.", "로그인하거나 다른 이메일을 쓰세요.")
    user = User(email=email, password_hash=hash_password(body.password), name=body.name)
    db.add(user)
    db.flush()
    ws = create_workspace(db, user, body.workspace_name or f"{body.name}의 워크스페이스")
    audit(
        db,
        workspace_id=ws.id,
        user_id=user.id,
        action="auth.signup",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return create_tokens(user.id)


@router.post("/auth/login")
def login(body: LoginIn, db: DbDep) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise AppError(
            401, "이메일 또는 비밀번호가 맞지 않아요.", "입력한 내용을 확인하고 다시 시도하세요."
        )
    return create_tokens(user.id)


@router.post("/auth/refresh")
def refresh(body: RefreshIn, db: DbDep) -> dict[str, str]:
    user_id = decode_token(body.refresh_token, "refresh")
    if not user_id or db.get(User, user_id) is None:
        raise AppError(401, "로그인이 만료됐어요.", "다시 로그인하세요.")
    return create_tokens(user_id)


def _invitation(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token == token))
    if inv is None:
        raise not_found("초대")
    return inv


def _expired(inv: Invitation) -> bool:
    exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=UTC)
    return exp < datetime.now(UTC)


@router.get("/auth/invitations/{token}")
def get_invitation(token: str, db: DbDep) -> dict[str, Any]:
    inv = _invitation(db, token)
    ws = db.get(Workspace, inv.workspace_id)
    return {
        "email": inv.email,
        "role": inv.role,
        "workspace_name": ws.name if ws else "",
        "expired": _expired(inv),
        "accepted": inv.accepted_at is not None,
    }


@router.post("/auth/invitations/{token}/accept")
def accept_invitation(token: str, body: AcceptIn, db: DbDep) -> dict[str, str]:
    inv = _invitation(db, token)
    if inv.accepted_at is not None:
        raise AppError(409, "이미 수락한 초대예요.", "로그인 화면에서 로그인하세요.")
    if _expired(inv):
        raise AppError(
            410, "초대 기간이 지났어요.", "관리자에게 초대를 다시 보내 달라고 요청하세요."
        )
    user = db.scalar(select(User).where(User.email == inv.email.lower()))
    if user is None:
        user = User(
            email=inv.email.lower(), password_hash=hash_password(body.password), name=body.name
        )
        db.add(user)
        db.flush()
    elif not verify_password(body.password, user.password_hash):
        raise AppError(
            401, "이미 있는 계정의 비밀번호가 맞지 않아요.", "기존 비밀번호를 입력하세요."
        )
    exists = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == inv.workspace_id
        )
    )
    if exists is None:
        db.add(Membership(user_id=user.id, workspace_id=inv.workspace_id, role=inv.role))
    inv.accepted_at = datetime.now(UTC)
    audit(
        db,
        workspace_id=inv.workspace_id,
        user_id=user.id,
        action="member.join",
        target_type="user",
        target_id=user.id,
        meta={"role": inv.role},
    )
    db.commit()
    return create_tokens(user.id)


@router.get("/me")
def me(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    rows = db.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.name)
    ).all()
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug, "role": r} for w, r in rows],
    }
