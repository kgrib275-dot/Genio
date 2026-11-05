"""v0.7 계정 스스로 관리: 비밀번호 찾기, 이메일 인증, 2단계 인증, 로그인 기기, 내 데이터, 탈퇴,
시스템 메일 설정. 로그인 전 엔드포인트는 공개(속도 제한), 나머지는 로그인 필요(CurrentUser).
시스템 메일 설정은 인스턴스 관리자(첫 워크스페이스 소유자)만 쓴다.
"""

import contextlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core import ratelimit, totp
from api.core.audit import audit
from api.core.crypto import decrypt_str, encrypt_str
from api.core.errors import AppError
from api.core.password_policy import check_password
from api.core.security import decode_payload, hash_password, verify_password
from api.deps import CurrentUser, DbDep
from api.models import User
from api.routers.common import client_ip, public_origin
from api.services import accounts, mailer, system

router = APIRouter(tags=["account"])

SAME_ANSWER = {
    "ok": True,
    "message": "가입된 이메일이면 몇 분 안에 메일이 도착해요.",
    "hint": "메일이 안 보이면 스팸함을 확인하고, 그래도 없으면 잠시 뒤 다시 요청하세요.",
}


def _limit(key: str, limit: int = 5, window: int = 900) -> None:
    if not ratelimit.allow(key, limit, window):
        raise AppError(429, "요청이 너무 많아 잠시 막았어요.", "15분쯤 뒤에 다시 시도하세요.")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------- 비밀번호 찾기 ----------------
class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/auth/password/forgot")
def forgot_password(body: ForgotIn, request: Request, db: DbDep) -> dict[str, Any]:
    """있는 계정인지 알 수 없게 늘 같은 답을 준다(메일 설정이 없을 때만 다르게 알림)."""
    email = body.email.strip().lower()
    _limit(f"forgot:{client_ip(request)}", 10)
    _limit(f"forgot:{email}", 3)
    if not mailer.configured(db):
        raise mailer.MailNotConfiguredError()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.password_hash != accounts.DELETED_HASH:
        raw = accounts.make_link_token(db, user, "reset")
        link = f"{public_origin(request)}/reset-password?token={raw}"
        with contextlib.suppress(AppError):  # 실패해도 같은 답(계정이 있는지 숨긴다)
            mailer.send(
                db,
                user.email,
                "[Genio] 비밀번호 다시 정하기",
                f"{user.name}님, 비밀번호를 다시 정하려면 아래 링크를 여세요(30분 안, 한 번만).\n"
                f"{link}\n\n직접 요청하지 않았다면 이 메일은 무시하세요. 비밀번호는 그대로예요.",
            )
        audit(
            db,
            workspace_id=None,
            user_id=user.id,
            action="auth.password_reset_request",
            target_type="user",
            target_id=user.id,
            meta={"ip": client_ip(request)},
        )
        db.commit()
    return SAME_ANSWER


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/password/reset")
def reset_password(body: ResetIn, request: Request, db: DbDep) -> dict[str, Any]:
    _limit(f"reset:{client_ip(request)}", 20)
    user = accounts.use_link_token(db, body.token, "reset")
    check_password(body.password, user.email)
    user.password_hash = hash_password(body.password)
    user.must_change_password = False
    # 메일을 열었으니 이메일도 확인된 것. 다른 기기의 로그인은 모두 끊는다
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    db.commit()
    accounts.revoke_all(db, user)
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="auth.password_reset",
        target_type="user",
        target_id=user.id,
        meta={"ip": client_ip(request)},
    )
    db.commit()
    return {"ok": True, "message": "새 비밀번호로 바꿨어요. 다시 로그인하세요."}


# ---------------- 이메일 인증 ----------------
class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/auth/verify-email")
def verify_email(body: TokenIn, request: Request, db: DbDep) -> dict[str, Any]:
    _limit(f"verify:{client_ip(request)}", 20)
    user = accounts.use_link_token(db, body.token, "verify")
    user.email_verified_at = user.email_verified_at or _now()
    db.commit()
    return {"ok": True, "message": "이메일 확인이 끝났어요. 로그인하세요."}


@router.post("/auth/verify-email/resend")
def resend_verify_public(body: ForgotIn, request: Request, db: DbDep) -> dict[str, Any]:
    """로그인 전(인증 필수일 때) 다시 보내기. 늘 같은 답."""
    from api.routers.auth import send_verify_mail

    email = body.email.strip().lower()
    _limit(f"resend:{client_ip(request)}", 10)
    _limit(f"resend:{email}", 3)
    if not mailer.configured(db):
        raise mailer.MailNotConfiguredError()
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.email_verified_at is None:
        with contextlib.suppress(AppError):
            send_verify_mail(db, user, request)
    return SAME_ANSWER


@router.post("/me/verify-email/resend")
def resend_verify_me(user: CurrentUser, request: Request, db: DbDep) -> dict[str, Any]:
    from api.routers.auth import send_verify_mail

    if user.email_verified_at is not None:
        return {"ok": True, "message": "이미 확인된 이메일이에요."}
    _limit(f"resend:{user.email}", 3)
    send_verify_mail(db, user, request)
    return {"ok": True, "message": f"{user.email}으로 확인 메일을 보냈어요."}


# ---------------- 2단계 인증 ----------------
class MfaLoginIn(BaseModel):
    mfa_token: str = Field(min_length=10, max_length=2000)
    code: str = Field(min_length=6, max_length=20)


def _check_second_factor(db: DbDep, user: User, code: str) -> bool:
    """앱 코드 6자리 또는 복구 코드(한 번 쓰면 사라짐)."""
    if user.totp_secret_encrypted and totp.verify(
        decrypt_str(user.totp_secret_encrypted.encode()), code
    ):
        return True
    h = totp.hash_code(code)
    codes = list(user.recovery_codes or [])
    if h in codes:
        codes.remove(h)
        user.recovery_codes = codes
        db.commit()
        return True
    return False


@router.post("/auth/login/mfa")
def login_mfa(body: MfaLoginIn, request: Request, db: DbDep) -> dict[str, Any]:
    payload = decode_payload(body.mfa_token, "mfa")
    user = db.get(User, str(payload["sub"])) if payload else None
    if payload is None or user is None or not user.totp_enabled:
        raise AppError(401, "로그인 시간이 지났어요.", "처음부터 다시 로그인하세요.")
    key = f"mfa:{user.id}"
    window = 900
    if ratelimit.fail_count(key, window) >= 5:
        raise AppError(429, "코드를 너무 많이 틀렸어요.", "15분 뒤에 다시 로그인하세요.")
    if not _check_second_factor(db, user, body.code):
        ratelimit.add_fail(key, window)
        raise AppError(
            401,
            "인증 코드가 맞지 않아요.",
            "인증 앱의 지금 6자리 숫자나 복구 코드를 넣으세요. 휴대폰 시간이 맞는지도 확인하세요.",
        )
    ratelimit.clear_fails(key)
    return accounts.issue_tokens(db, user, request)


@router.post("/me/2fa/setup")
def setup_2fa(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    """새 비밀값을 만들어 돌려준다(아직 켜지지 않음). 앱에 등록한 뒤 코드로 확인해야 켜진다."""
    if user.totp_enabled:
        raise AppError(
            409, "이미 2단계 인증을 쓰고 있어요.", "다시 설정하려면 먼저 끄고 시작하세요."
        )
    secret = totp.new_secret()
    user.totp_secret_encrypted = encrypt_str(secret).decode()
    db.commit()
    return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, user.email)}


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


@router.post("/me/2fa/enable")
def enable_2fa(body: CodeIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    if user.totp_enabled:
        raise AppError(409, "이미 2단계 인증을 쓰고 있어요.", "내 설정 화면을 새로고침하세요.")
    if not user.totp_secret_encrypted:
        raise AppError(400, "설정을 먼저 시작해야 해요.", "'2단계 인증 켜기'를 다시 누르세요.")
    if not totp.verify(decrypt_str(user.totp_secret_encrypted.encode()), body.code):
        raise AppError(
            400,
            "인증 코드가 맞지 않아요.",
            "앱에 보이는 지금 6자리 숫자를 넣으세요. 휴대폰 시간이 자동인지 확인하세요.",
        )
    codes = totp.recovery_codes()
    user.recovery_codes = [totp.hash_code(c) for c in codes]
    user.totp_enabled = True
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="auth.2fa_enable",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return {"enabled": True, "recovery_codes": codes}


class PasswordCodeIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=20)


def _need_password(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise AppError(400, "비밀번호가 맞지 않아요.", "지금 쓰는 비밀번호를 넣으세요.")


@router.post("/me/2fa/disable")
def disable_2fa(body: PasswordCodeIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _need_password(user, body.password)
    if user.totp_enabled and not _check_second_factor(db, user, body.code or ""):
        raise AppError(400, "인증 코드가 맞지 않아요.", "앱의 6자리 숫자나 복구 코드를 넣으세요.")
    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.recovery_codes = []
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="auth.2fa_disable",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return {"enabled": False}


@router.post("/me/2fa/recovery-codes")
def new_recovery_codes(body: PasswordCodeIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _need_password(user, body.password)
    if not user.totp_enabled:
        raise AppError(400, "2단계 인증이 꺼져 있어요.", "먼저 2단계 인증을 켜세요.")
    codes = totp.recovery_codes()
    user.recovery_codes = [totp.hash_code(c) for c in codes]
    db.commit()
    return {"recovery_codes": codes}


# ---------------- 로그인 기기 ----------------
@router.get("/me/sessions")
def my_sessions(user: CurrentUser, request: Request, db: DbDep) -> list[dict[str, Any]]:
    return accounts.list_sessions(db, user, getattr(request.state, "session_id", None))


@router.delete("/me/sessions/{session_id}", status_code=204)
def revoke_my_session(session_id: str, user: CurrentUser, db: DbDep) -> Response:
    accounts.revoke_session(db, user, session_id)
    return Response(status_code=204)


@router.post("/me/sessions/revoke-all")
def revoke_all_sessions(user: CurrentUser, request: Request, db: DbDep) -> dict[str, Any]:
    """다른 모든 기기에서 로그아웃. 이 기기는 새 토큰으로 계속 쓴다."""
    current = getattr(request.state, "session_id", None)
    accounts.revoke_all(db, user, keep=current)
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="auth.logout_all",
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return accounts.issue_tokens(db, user, request, current)


# ---------------- 내 데이터·탈퇴 ----------------
@router.get("/me/export")
def export_me(user: CurrentUser, db: DbDep) -> Response:
    data = accounts.export_user(db, user)
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="genio-my-data.json"'},
    )


class DeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: Literal["탈퇴"]


@router.post("/me/delete")
def delete_me(body: DeleteIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _need_password(user, body.password)
    blockers = accounts.sole_owner_blockers(db, user)
    if blockers:
        raise AppError(
            409,
            f"'{', '.join(blockers)}' 워크스페이스의 하나뿐인 소유자라 탈퇴할 수 없어요.",
            "관리 > 멤버에서 다른 사람에게 소유권을 넘긴 뒤 다시 시도하세요.",
        )
    uid = user.id
    accounts.anonymize(db, user)
    audit(
        db,
        workspace_id=None,
        user_id=uid,
        action="auth.account_delete",
        target_type="user",
        target_id=uid,
    )
    db.commit()
    return {"ok": True, "message": "탈퇴했어요. 그동안 이용해 주셔서 고마워요."}


# ---------------- 시스템 메일(인스턴스 관리자) ----------------
def _instance_admin(db: DbDep, user: User) -> None:
    if not system.is_instance_admin(db, user.id):
        raise AppError(
            403,
            "시스템 설정은 인스턴스 관리자만 바꿀 수 있어요.",
            "가장 먼저 만든 워크스페이스의 소유자에게 요청하세요.",
        )


@router.get("/admin/system/mail")
def get_mail(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _instance_admin(db, user)
    return mailer.public_settings(db)


class MailIn(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    from_addr: str | None = Field(default=None, max_length=320)
    from_name: str | None = Field(default=None, max_length=100)
    security: str | None = None


@router.put("/admin/system/mail")
def put_mail(body: MailIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _instance_admin(db, user)
    out = mailer.save_settings(db, body.model_dump(exclude_unset=True))
    audit(
        db,
        workspace_id=system.instance_workspace_id(db),
        user_id=user.id,
        action="system.mail_update",
        target_type="system",
        meta={"host": out["host"], "from": out["from_addr"]},
    )
    db.commit()
    return out


@router.post("/admin/system/mail/test")
def test_mail(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _instance_admin(db, user)
    mailer.send(
        db,
        user.email,
        "[Genio] 시험 메일",
        "시스템 메일 설정이 잘 되었어요. 비밀번호 찾기·이메일 인증 메일이 이 주소로 나가요.",
    )
    return {"ok": True, "message": f"{user.email}으로 시험 메일을 보냈어요."}
