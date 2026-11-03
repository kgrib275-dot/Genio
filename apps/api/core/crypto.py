"""비밀값 Fernet 암호화와 마스킹. 비밀값은 로그·응답·오류에 절대 내보내지 않는다."""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from api.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().genio_fernet_key.strip()
    if not key:
        # 개발 편의: 키가 없으면 SECRET_KEY에서 파생한다. 운영에서는 반드시 GENIO_FERNET_KEY를 둔다.
        digest = hashlib.sha256(get_settings().genio_secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt_str(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_str(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("암호화된 값을 풀 수 없어요. 암호화 키가 바뀌었는지 확인하세요.") from exc


def encrypt_json(value: dict[str, Any]) -> bytes:
    return encrypt_str(json.dumps(value, ensure_ascii=False))


def decrypt_json(token: bytes) -> dict[str, Any]:
    data = json.loads(decrypt_str(token))
    if not isinstance(data, dict):
        raise ValueError("저장된 비밀값 형식이 올바르지 않아요.")
    return data


def mask(value: str) -> str:
    """마지막 4자리만 남긴다: ****abcd"""
    tail = value[-4:] if len(value) >= 8 else ""
    return f"****{tail}"


def redact(text: str, secrets: list[str]) -> str:
    """로그·오류 문자열에서 비밀값을 지운다."""
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, mask(s))
    return text
