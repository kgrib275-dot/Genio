"""인증·내 정보. 로그인 전 엔드포인트라 require_role 대신 공개(또는 로그인만 필요)다."""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.core.password_policy import check_password
from api.core.security import (
    create_tokens,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from api.deps import CurrentUser, DbDep
from api.models import Invitation, Membership, Organization, User, Workspace
from api.routers.common import client_ip
from api.services import system
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
    if not system.get_system(db)["allow_signup"]:
        raise AppError(403, "지금은 새로 가입할 수 없어요.", "관리자에게 초대 링크를 요청하세요.")
    email = body.email.lower()
    check_password(body.password, email)
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


def _too_many(minutes: int) -> AppError:
    return AppError(
        429,
        "로그인 시도가 너무 많아 잠시 막았어요.",
        f"{minutes}분 뒤에 다시 시도하거나 관리자에게 비밀번호 재설정을 요청하세요.",
    )


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: DbDep) -> dict[str, str]:
    s = get_settings()
    email = body.email.strip().lower()
    ip = client_ip(request)
    key_ip = f"login:{email}:{ip}"
    key_email = f"login:{email}"
    window = s.genio_login_lock_seconds
    # 무차별 대입 막기(부하 시험 보고서 §4): 이메일+IP 5번, 이메일 20번(15분)
    if (
        ratelimit.fail_count(key_ip, window) >= s.genio_login_max_fails
        or ratelimit.fail_count(key_email, window) >= s.genio_login_max_fails_per_email
    ):
        raise _too_many(max(1, window // 60))
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        ratelimit.add_fail(key_ip, window)
        ratelimit.add_fail(key_email, window)
        raise AppError(
            401,
            "이메일 또는 비밀번호가 맞지 않아요.",
            "한/영 키가 한글로 되어 있지 않은지, 이메일에 빈칸이 없는지 확인하고 다시 시도하세요.",
        )
    ratelimit.clear_fails(key_ip)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
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
        check_password(body.password, inv.email)
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
        "preferences": preferences_of(user),
        "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug, "role": r} for w, r in rows],
    }


# ---------------- 개인 설정 ----------------
PREF_DEFAULTS: dict[str, Any] = {
    "theme": "system",  # light | dark | system
    "font_size": "normal",  # normal | large
    "default_workspace_id": None,
    "enter_to_send": True,
    # v0.6: 화면 목록마다 고른 한 번에 보기 개수·필터(계정별로 유지). {목록 이름: {size, filters}}
    "lists": {},
}
MAX_LIST_PREFS = 200


def preferences_of(user: User) -> dict[str, Any]:
    return {
        **PREF_DEFAULTS,
        **{k: v for k, v in (user.preferences or {}).items() if k in PREF_DEFAULTS},
    }


class PreferencesIn(BaseModel):
    theme: Literal["light", "dark", "system"] | None = None
    font_size: Literal["normal", "large"] | None = None
    default_workspace_id: str | None = None
    enter_to_send: bool | None = None
    lists: dict[str, "ListPref"] | None = None


class ListPref(BaseModel):
    size: Literal[10, 20, 50, 100] | None = None
    filters: dict[str, str] | None = Field(default=None, max_length=20)


PreferencesIn.model_rebuild()


class MePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    preferences: PreferencesIn | None = None


@router.patch("/me")
def update_me(body: MePatch, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    if body.name:
        user.name = body.name.strip()
    if body.preferences is not None:
        patch = body.preferences.model_dump(exclude_unset=True)
        ws = patch.get("default_workspace_id")
        if (
            ws
            and db.scalar(
                select(Membership).where(
                    Membership.user_id == user.id, Membership.workspace_id == ws
                )
            )
            is None
        ):
            raise AppError(
                404, "그 워크스페이스의 멤버가 아니에요.", "목록에 있는 워크스페이스를 고르세요."
            )
        current = preferences_of(user)
        if "lists" in patch:
            # 목록별로 합친다(한 화면을 저장해도 다른 화면 설정은 그대로)
            merged = dict(current.get("lists") or {})
            for key, pref in (patch.pop("lists") or {}).items():
                clean = {k: v for k, v in (pref or {}).items() if v is not None}
                if clean.get("filters"):
                    clean["filters"] = {
                        str(fk)[:40]: str(fv)[:200] for fk, fv in clean["filters"].items() if fv
                    }
                merged[str(key)[:80]] = {**(merged.get(str(key)[:80]) or {}), **clean}
            if len(merged) > MAX_LIST_PREFS:
                merged = dict(list(merged.items())[-MAX_LIST_PREFS:])
            current["lists"] = merged
        user.preferences = {**current, **patch}
    db.commit()
    return me(user, db)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/me/password")
def change_password(body: PasswordIn, user: CurrentUser, db: DbDep) -> dict[str, bool]:
    if not verify_password(body.current_password, user.password_hash):
        raise AppError(400, "지금 비밀번호가 맞지 않아요.", "한/영 키를 확인하고 다시 입력하세요.")
    if body.current_password == body.new_password:
        raise AppError(400, "새 비밀번호가 지금과 같아요.", "다른 비밀번호를 정하세요.")
    check_password(body.new_password, user.email)
    user.password_hash = hash_password(body.new_password)
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="auth.password_change",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return {"ok": True}
