"""비밀번호(bcrypt)와 JWT(access 15분, refresh 7일)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from api.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def _encode(sub: str, kind: str, delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "type": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, get_settings().genio_secret_key, algorithm=ALGORITHM)


def create_tokens(user_id: str) -> dict[str, str]:
    s = get_settings()
    return {
        "access_token": _encode(user_id, "access", timedelta(minutes=s.access_token_minutes)),
        "refresh_token": _encode(user_id, "refresh", timedelta(days=s.refresh_token_days)),
        "token_type": "bearer",
    }


def decode_token(token: str, kind: str) -> str | None:
    """유효하면 user_id, 아니면 None."""
    try:
        payload = jwt.decode(token, get_settings().genio_secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != kind:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)
