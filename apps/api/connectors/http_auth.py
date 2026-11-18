"""HTTP 단계·시험 호출의 인증 헤더 만들기(기능 정의서 §4 범용 HTTP).

auth = {
  "type": "none" | "bearer" | "basic" | "header",
  "credential_id": "<연결 정보 id>",   # 마켓 'http_credentials'(HTTP 인증 정보)로 만든 것
  "header_name": "X-API-Key"          # type=header일 때. 비워 두면 연결 정보의 header_name
}
비밀값은 연결 정보에서만 꺼낸다(단계 설정에 직접 적지 않는다). 반환한 헤더는 로그에 남기지 않는다.

운영 준비 1차(B1·F4): 연결 정보에 '보낼 수 있는 주소'(allowed_hosts, 쉼표로 구분)를 적어 두면
그 호스트(또는 하위 도메인)로 가는 요청에만 인증 헤더를 붙인다. 빌더나 다른 사람이 만든 흐름이
비밀값을 엉뚱한 주소로 보내지 못하게 한다. 비워 두면 예전처럼 어느 주소에나 쓸 수 있다.
"""

import base64
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from api.core.crypto import decrypt_json
from api.models import ConnectorCredential, ConnectorDefinition
from nodes import NodeError

AUTH_TYPES = ("none", "bearer", "basic", "header")
CREDENTIAL_KEY = "http_credentials"
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _secrets(db: Session, workspace_id: str, credential_id: str) -> dict[str, Any]:
    cred = db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError(
            "HTTP 인증에 쓸 연결 정보를 찾을 수 없어요. 단계 설정에서 다시 골라 주세요."
        )
    d = db.get(ConnectorDefinition, cred.definition_id)
    if d is None or d.key != CREDENTIAL_KEY:
        raise NodeError("HTTP 인증에는 'HTTP 인증 정보' 연결 정보만 쓸 수 있어요.")
    data = decrypt_json(cred.secret_encrypted)
    return data if isinstance(data, dict) else {}


def parse_hosts(raw: Any) -> list[str]:
    """'api.example.com, *.foo.kr' → ['api.example.com', 'foo.kr'] (앞의 *. 와 공백은 지운다)."""
    out: list[str] = []
    for part in re.split(r"[,\s]+", str(raw or "")):
        h = part.strip().lower()
        h = h.removeprefix("*.").removeprefix("https://").removeprefix("http://").split("/")[0]
        if h and h not in out:
            out.append(h)
    return out


def host_allowed(url: str, allowed: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and any(host == h or host.endswith("." + h) for h in allowed)


def check_destination(secrets: dict[str, Any], url: str | None) -> None:
    allowed = parse_hosts(secrets.get("allowed_hosts"))
    if not allowed:
        return
    if not url or not host_allowed(url, allowed):
        host = urlparse(url or "").hostname or "?"
        raise NodeError(
            f"이 연결 정보는 '{host}' 주소에는 쓸 수 없어요(허용: {', '.join(allowed)}).\n"
            "주소를 확인하거나, 연결 정보의 '보낼 수 있는 주소'에 이 주소를 더해 주세요."
        )


def auth_headers(
    db: Session, workspace_id: str, auth: dict[str, Any] | None, *, url: str | None = None
) -> dict[str, str]:
    """인증 설정에 맞는 요청 헤더. type이 none이거나 auth가 비어 있으면 빈 dict.

    url: 이 헤더를 보낼 주소. 연결 정보에 '보낼 수 있는 주소'가 있으면 맞는지 확인한다.
    """
    if not auth:
        return {}
    kind = str(auth.get("type") or "none")
    if kind not in AUTH_TYPES:
        raise NodeError(
            "HTTP 인증 방식을 알 수 없어요. 없음·Bearer 토큰·아이디/비밀번호·헤더 중에서 고르세요."
        )
    if kind == "none":
        return {}
    cred_id = str(auth.get("credential_id") or "")
    if not cred_id:
        raise NodeError("HTTP 인증에 쓸 연결 정보를 골라 주세요.")
    s = _secrets(db, workspace_id, cred_id)
    check_destination(s, url)
    if kind == "bearer":
        token = str(s.get("token") or "")
        if not token:
            raise NodeError("연결 정보에 토큰이 없어요. 'HTTP 인증 정보'에 토큰을 넣어 주세요.")
        return {"Authorization": f"Bearer {token}"}
    if kind == "basic":
        user, pw = str(s.get("username") or ""), str(s.get("password") or "")
        if not user:
            raise NodeError("연결 정보에 아이디가 없어요. 'HTTP 인증 정보'를 확인하세요.")
        raw = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}
    name = str(auth.get("header_name") or s.get("header_name") or "").strip()
    value = str(s.get("header_value") or "")
    if not _HEADER_NAME.match(name):
        raise NodeError("헤더 이름이 올바르지 않아요(영문·숫자·하이픈만). 예: X-API-Key")
    if not value:
        raise NodeError("연결 정보에 헤더 값이 없어요. 'HTTP 인증 정보'를 확인하세요.")
    return {name: value}
