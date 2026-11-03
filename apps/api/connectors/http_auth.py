"""HTTP 단계·시험 호출의 인증 헤더 만들기(기능 정의서 §4 범용 HTTP).

auth = {
  "type": "none" | "bearer" | "basic" | "header",
  "credential_id": "<연결 정보 id>",   # 마켓 'http_credentials'(HTTP 인증 정보)로 만든 것
  "header_name": "X-API-Key"          # type=header일 때. 비워 두면 연결 정보의 header_name
}
비밀값은 연결 정보에서만 꺼낸다(단계 설정에 직접 적지 않는다). 반환한 헤더는 로그에 남기지 않는다.
"""

import base64
import re
from typing import Any

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


def auth_headers(db: Session, workspace_id: str, auth: dict[str, Any] | None) -> dict[str, str]:
    """인증 설정에 맞는 요청 헤더. type이 none이거나 auth가 비어 있으면 빈 dict."""
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
