"""메신저(슬랙·팀즈)에서 앱 부르기.

공유 링크로 배포한 앱 하나를 슬랙 슬래시 명령(/제니오 질문)이나 팀즈 '나가는 웹훅'(@제니오 질문)으로 부른다.
서명 비밀값은 배포(deployment.appearance["_messenger"])에 암호화해 두고, 화면·응답에는 절대 내보내지 않는다.
요청이 슬랙·팀즈에서 온 것인지는 서명(HMAC)으로만 믿는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from typing import Any

from api.core.crypto import decrypt_str, encrypt_str, mask
from api.core.errors import AppError
from api.models import Deployment

KEY = "_messenger"
PROVIDERS = ("slack", "teams")
SLACK_MAX_AGE_SECONDS = 300
MAX_QUESTION = 2000
SLACK_RESPONSE_HOSTS = ("hooks.slack.com",)


def _store(dep: Deployment) -> dict[str, str]:
    raw = (dep.appearance or {}).get(KEY) or {}
    return {k: str(v) for k, v in raw.items() if k in PROVIDERS and v}


def set_secret(dep: Deployment, provider: str, secret: str) -> None:
    if provider not in PROVIDERS:
        raise AppError(422, "지원하지 않는 메신저예요.", "슬랙 또는 팀즈를 고르세요.")
    secret = secret.strip()
    if len(secret) < 8:
        raise AppError(
            422,
            "서명 비밀값이 너무 짧아요.",
            "슬랙 앱 설정의 Signing Secret을 그대로 붙여 넣으세요.",
        )
    store = _store(dep)
    store[provider] = encrypt_str(secret).decode("ascii")
    dep.appearance = {**(dep.appearance or {}), KEY: store}


def clear_secret(dep: Deployment, provider: str) -> None:
    store = _store(dep)
    store.pop(provider, None)
    dep.appearance = {**(dep.appearance or {}), KEY: store}


def get_secret(dep: Deployment, provider: str) -> str | None:
    enc = _store(dep).get(provider)
    if not enc:
        return None
    try:
        return decrypt_str(enc.encode("ascii"))
    except Exception:
        return None


def status(dep: Deployment) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in PROVIDERS:
        s = get_secret(dep, p)
        out[p] = {"configured": s is not None, "hint": mask(s) if s else ""}
    return out


# ---------------- 슬랙 ----------------
def slack_signature(secret: str, timestamp: str, body: bytes) -> str:
    base = f"v0:{timestamp}:".encode() + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def verify_slack(
    secret: str, timestamp: str, signature: str, body: bytes, now: float | None = None
) -> bool:
    try:
        age = abs((now if now is not None else time.time()) - float(timestamp))
    except ValueError:
        return False
    if age > SLACK_MAX_AGE_SECONDS:
        return False
    return hmac.compare_digest(slack_signature(secret, timestamp, body), signature)


def valid_slack_response_url(url: str) -> bool:
    from urllib.parse import urlparse

    p = urlparse(url)
    return p.scheme == "https" and (p.hostname or "") in SLACK_RESPONSE_HOSTS


# ---------------- 팀즈 ----------------
def teams_signature(secret: str, body: bytes) -> str:
    key = base64.b64decode(secret)
    return "HMAC " + base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode()


def verify_teams(secret: str, authorization: str, body: bytes) -> bool:
    try:
        expected = teams_signature(secret, body)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, authorization.strip())


def clean_question(text: str) -> str:
    """팀즈의 '<at>제니오</at>' 멘션과 앞뒤 공백을 뺀다."""
    out = re.sub(r"<at>.*?</at>", "", text or "", flags=re.S)
    out = re.sub(r"<[^>]+>", "", out)  # 팀즈가 붙이는 HTML 조각
    return out.replace("&nbsp;", " ").strip()[:MAX_QUESTION]
