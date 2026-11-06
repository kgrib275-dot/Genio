"""2단계 인증(TOTP, RFC 6238 / HOTP RFC 4226). 표준 라이브러리만 쓴다.

구글 OTP·마이크로소프트 Authenticator 같은 앱과 같은 방식(SHA1, 6자리, 30초)이다.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30


def new_secret() -> str:
    """앱에 넣을 비밀값(Base32, 160비트)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    pad = "=" * (-len(secret) % 8)
    return base64.b32decode(secret.upper() + pad)


def hotp(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**DIGITS)
    return str(code).zfill(DIGITS)


def totp(secret: str, at: float | None = None) -> str:
    return hotp(secret, int((at if at is not None else time.time()) // PERIOD))


def verify(secret: str, code: str, at: float | None = None, window: int = 1) -> bool:
    """앞뒤 30초(window=1)까지 맞으면 통과. 시계가 조금 어긋나도 된다."""
    code = "".join(ch for ch in str(code) if ch in "0123456789")
    if len(code) != DIGITS:
        return False
    now = int((at if at is not None else time.time()) // PERIOD)
    return any(hmac.compare_digest(hotp(secret, now + d), code) for d in range(-window, window + 1))


def otpauth_uri(secret: str, account: str, issuer: str = "Genio") -> str:
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def recovery_codes(n: int = 10) -> list[str]:
    """한 번씩 쓰는 복구 코드(xxxx-xxxx)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    out = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()
