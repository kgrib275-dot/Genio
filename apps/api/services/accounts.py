"""v0.7 계정 스스로 관리: 로그인 기기(세션), 한 번 쓰는 링크 토큰, 내 데이터 내려받기, 탈퇴.

- 토큰 확인: 발급 시각(iat)이 users.tokens_valid_after보다 이르면 무효,
  기기(sid)가 끊겼으면 무효. 오래된(sid 없는) 토큰은 시각 규칙만 따른다.
- 링크 토큰은 원문 대신 SHA-256 해시만 저장하고 한 번 쓰면 끝난다.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.core.security import create_tokens
from api.models import (
    App,
    AuditLog,
    AuthToken,
    Conversation,
    Membership,
    User,
    UserSession,
    Workspace,
)

TOUCH_EVERY = timedelta(minutes=5)
# 탈퇴한 계정의 비밀번호 칸(어떤 비밀번호와도 맞지 않는다)
DELETED_HASH = "!deleted"
RESET_MINUTES = 30
VERIFY_HOURS = 48


def now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ---------------- 기기(세션) ----------------
def _client(request: Request | None) -> tuple[str, str]:
    if request is None:
        return "", ""
    from api.routers.common import client_ip

    ua = (request.headers.get("user-agent") or "")[:300]
    return ua, client_ip(request)[:64]


def issue_tokens(
    db: Session, user: User, request: Request | None, sid: str | None = None
) -> dict[str, str]:
    """로그인·가입 성공: 새 기기를 만들고(또는 이어 쓰고) 토큰을 준다."""
    if sid is None:
        ua, ip = _client(request)
        sess = UserSession(user_id=user.id, user_agent=ua, ip=ip, last_seen_at=now())
        db.add(sess)
        db.commit()
        sid = sess.id
    return create_tokens(user.id, sid)


def token_still_valid(db: Session, user: User, payload: dict[str, Any]) -> bool:
    if user.password_hash == DELETED_HASH:
        return False  # 탈퇴한 계정
    after = _aware(user.tokens_valid_after)
    # iat는 초 단위라, 같은 초 안에 무효로 한 시각(소수점 있음)보다 앞이면 끊긴다
    if after is not None and int(payload.get("iat") or 0) < after.timestamp():
        return False
    sid = payload.get("sid")
    if not sid:
        return True
    sess = db.get(UserSession, str(sid))
    if sess is None or sess.user_id != user.id or sess.revoked_at is not None:
        return False
    last = _aware(sess.last_seen_at)
    if last is None or now() - last > TOUCH_EVERY:
        sess.last_seen_at = now()
        db.commit()
    return True


def list_sessions(db: Session, user: User, current: str | None) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    )
    return [
        {
            "id": s.id,
            "user_agent": s.user_agent,
            "ip": s.ip,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
            "current": s.id == current,
        }
        for s in rows
    ]


def revoke_session(db: Session, user: User, session_id: str) -> None:
    sess = db.get(UserSession, session_id)
    if sess is None or sess.user_id != user.id:
        raise AppError(404, "그 기기를 찾지 못했어요.", "목록을 새로고침해 다시 확인하세요.")
    sess.revoked_at = now()
    db.commit()


def revoke_all(db: Session, user: User, keep: str | None = None) -> None:
    """모든 기기에서 로그아웃(keep 기기만 남김). sid 없는 예전 토큰도 시각 규칙으로 끊는다."""
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.id != (keep or ""),
        )
        .values(revoked_at=now())
    )
    # 1초 앞으로: 같은 초에 다시 발급하는 지금 기기 토큰은 통과하게
    user.tokens_valid_after = now().replace(microsecond=0)
    db.commit()


# ---------------- 한 번 쓰는 링크 토큰 ----------------
def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def make_link_token(db: Session, user: User, kind: str) -> str:
    raw = secrets.token_urlsafe(32)
    life = timedelta(minutes=RESET_MINUTES) if kind == "reset" else timedelta(hours=VERIFY_HOURS)
    # 같은 종류의 쓰지 않은 예전 링크는 모두 끝낸다
    db.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.kind == kind, AuthToken.used_at.is_(None))
        .values(used_at=now())
    )
    db.add(AuthToken(user_id=user.id, kind=kind, token_hash=_hash(raw), expires_at=now() + life))
    db.commit()
    return raw


def use_link_token(db: Session, raw: str, kind: str) -> User:
    bad = AppError(
        400,
        "링크가 맞지 않거나 시간이 지났어요.",
        "처음부터 다시 요청해 새 메일의 링크를 여세요.",
    )
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == _hash(raw or "")))
    if row is None or row.kind != kind or row.used_at is not None:
        raise bad
    exp = _aware(row.expires_at)
    if exp is None or exp < now():
        raise bad
    user = db.get(User, row.user_id)
    if user is None:
        raise bad
    row.used_at = now()
    return user


# ---------------- 내 데이터 ----------------
def export_user(db: Session, user: User) -> dict[str, Any]:
    """내 정보를 JSON으로(비밀값·비밀번호 해시·2단계 비밀값 제외)."""
    members = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
    ws_names = {
        w.id: w.name
        for w in db.scalars(
            select(Workspace).where(Workspace.id.in_([m.workspace_id for m in members] or [""]))
        )
    }
    apps = db.scalars(select(App).where(App.created_by == user.id).order_by(App.updated_at))
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at)
    )
    audits = db.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(1000)
    )
    from api.models import Message

    def conv_dict(c: Conversation) -> dict[str, Any]:
        msgs = db.scalars(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
        )
        return {
            "id": c.id,
            "app_id": c.app_id,
            "created_at": c.created_at.isoformat(),
            "messages": [
                {"role": m.role, "content": m.content, "at": m.created_at.isoformat()} for m in msgs
            ],
        }

    return {
        "exported_at": now().isoformat(),
        "profile": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "created_at": user.created_at.isoformat(),
            "email_verified": user.email_verified_at is not None,
            "two_factor": bool(user.totp_enabled),
            "preferences": user.preferences or {},
        },
        "memberships": [
            {
                "workspace_id": m.workspace_id,
                "workspace": ws_names.get(m.workspace_id, ""),
                "role": m.role,
            }
            for m in members
        ],
        "apps_created": [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "workspace_id": a.workspace_id,
                "updated_at": a.updated_at.isoformat(),
            }
            for a in apps
        ],
        "conversations": [conv_dict(c) for c in convs],
        "activity": [
            {
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "at": a.created_at.isoformat(),
            }
            for a in audits
        ],
    }


def sole_owner_blockers(db: Session, user: User) -> list[str]:
    """내가 유일한 소유자인데 다른 멤버가 있는 워크스페이스 이름(탈퇴 전에 소유권을 넘겨야 함)."""
    names = []
    for m in db.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.role == "owner")
    ):
        owners = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == m.workspace_id, Membership.role == "owner")
        )
        others = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == m.workspace_id, Membership.user_id != user.id)
        )
        if (owners or 0) <= 1 and (others or 0) > 0:
            ws = db.get(Workspace, m.workspace_id)
            names.append(ws.name if ws else m.workspace_id)
    return names


def anonymize(db: Session, user: User) -> None:
    """탈퇴: 로그인 정보를 지우고 이름·이메일을 가린다. 멤버십·기기·링크는 지운다.

    만든 앱·대화 같은 업무 기록은 워크스페이스 자산이라 남기되 작성자는 '탈퇴한 사용자'로 보인다.
    """
    db.execute(delete(Membership).where(Membership.user_id == user.id))
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.name = "탈퇴한 사용자"
    user.password_hash = DELETED_HASH
    user.totp_secret_encrypted = None
    user.totp_enabled = False
    user.recovery_codes = []
    user.preferences = {}
    user.tokens_valid_after = now()
    db.commit()
