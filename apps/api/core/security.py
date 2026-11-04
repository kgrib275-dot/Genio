"""비밀번호(bcrypt)와 JWT(access 15분, refresh 7일)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from api.config import get_settings

ALGORITHM = "HS256"


# bcrypt 강도. 10은 OWASP 최소 권장치이고, 12(기본)보다 약 4배 빨라 로그인이 빠르다.
BCRYPT_ROUNDS = 10


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8")[:72], salt).decode("ascii")


def needs_rehash(password_hash: str) -> bool:
    """저장된 해시의 강도가 지금 설정과 다르면 True(로그인 성공 시 다시 저장)."""
    try:
        return int(password_hash.split("$")[2]) != BCRYPT_ROUNDS
    except (IndexError, ValueError):
        return True


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def _encode(sub: str, kind: str, delta: timedelta, sid: str | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "type": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if sid:
        # v0.7: 로그인한 기기(user_sessions.id). 그 기기를 끊으면 토큰이 통하지 않는다
        payload["sid"] = sid
    return jwt.encode(payload, get_settings().genio_secret_key, algorithm=ALGORITHM)


def create_tokens(user_id: str, sid: str | None = None) -> dict[str, str]:
    s = get_settings()
    return {
        "access_token": _encode(user_id, "access", timedelta(minutes=s.access_token_minutes), sid),
        "refresh_token": _encode(user_id, "refresh", timedelta(days=s.refresh_token_days), sid),
        "token_type": "bearer",
    }


def create_short_token(user_id: str, kind: str, minutes: int = 5) -> str:
    """2단계 인증 대기 등 잠깐 쓰는 토큰."""
    return _encode(user_id, kind, timedelta(minutes=minutes))


def decode_payload(token: str, kind: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, get_settings().genio_secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != kind or not isinstance(payload.get("sub"), str):
        return None
    return dict(payload)


def decode_token(token: str, kind: str) -> str | None:
    """유효하면 user_id, 아니면 None."""
    payload = decode_payload(token, kind)
    return str(payload["sub"]) if payload else None


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
