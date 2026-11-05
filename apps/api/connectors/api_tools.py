"""API 도구(OpenAPI 가져오기, connector key 'api_tool_set') 실행.

도구 묶음은 연결 정보 한 건에 저장된다(암호화): 도구 목록(operations, JSON 글), 기본 주소, 인증 방식과
'HTTP 인증 정보' 연결 정보 id. 호출은 HTTP 단계와 같은 길(safe_http, auth_headers)로 나간다.
"""

import json
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.connectors.http_auth import auth_headers
from api.core.crypto import decrypt_json
from api.engine import safe_http
from api.models import ConnectorCredential, ConnectorDefinition
from nodes import NodeError

CREDENTIAL_KEY = "api_tool_set"
MAX_TEXT = 20_000


def load_set(db: Session, workspace_id: str, tool_set_id: str) -> dict[str, Any]:
    cred = db.get(ConnectorCredential, tool_set_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError("API 도구 묶음을 찾을 수 없어요. 단계 설정에서 다시 골라 주세요.")
    definition = db.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.id == cred.definition_id)
    )
    if definition is None or definition.key != CREDENTIAL_KEY:
        raise NodeError("API 도구 묶음이 아니에요. 'API 도구'로 가져온 묶음을 골라 주세요.")
    secrets = decrypt_json(cred.secret_encrypted)
    try:
        operations = json.loads(str(secrets.get("operations") or "[]"))
    except json.JSONDecodeError:
        raise NodeError("API 도구 묶음 내용이 깨졌어요. 명세를 다시 가져와 주세요.") from None
    return {
        "name": cred.name,
        "base_url": str(secrets.get("base_url") or "").rstrip("/"),
        "auth_type": str(secrets.get("auth_type") or "none"),
        "auth_credential_id": str(secrets.get("auth_credential_id") or ""),
        "operations": operations if isinstance(operations, list) else [],
    }


def find_operation(tool_set: dict[str, Any], operation: str) -> dict[str, Any]:
    for op in tool_set["operations"]:
        if isinstance(op, dict) and op.get("id") == operation:
            return op
    raise NodeError(
        f"'{operation}' 도구를 이 묶음에서 찾지 못했어요. 단계 설정에서 도구를 다시 골라 주세요."
    )


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_request(
    tool_set: dict[str, Any], op: dict[str, Any], params: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    """연산 설명과 넣은 값으로 (주소, 헤더)를 만든다. 빠진 필수 값은 한국어 오류로 알린다."""
    base = tool_set["base_url"]
    if not base:
        raise NodeError(
            "이 API 도구 묶음에 기본 주소가 없어요. 'API 도구'에서 기본 주소를 넣어 다시 가져오세요."
        )
    path = str(op["path"])
    query: list[tuple[str, str]] = []
    headers: dict[str, str] = {}
    missing: list[str] = []
    for p in op.get("parameters") or []:
        name, where = str(p["name"]), str(p["in"])
        value = params.get(name)
        if value in (None, ""):
            if p.get("required"):
                missing.append(name)
            elif p.get("default") is not None:
                value = p["default"]
            else:
                continue
        if value in (None, ""):
            continue
        if where == "path":
            path = path.replace("{" + name + "}", quote(_text(value), safe=""))
        elif where == "query":
            if isinstance(value, list):
                query.extend((name, _text(v)) for v in value)
            else:
                query.append((name, _text(value)))
        elif where == "header":
            headers[name] = _text(value)
    if missing:
        raise NodeError(f"도구에 꼭 필요한 값이 비어 있어요: {', '.join(missing)}")
    url = base + path
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query)
    return url, headers


def call(
    db: Session,
    workspace_id: str,
    *,
    tool_set_id: str,
    operation: str,
    params: dict[str, Any],
    body: Any,
) -> dict[str, Any]:
    tool_set = load_set(db, workspace_id, tool_set_id)
    op = find_operation(tool_set, operation)
    url, headers = build_request(tool_set, op, params)
    auth_type = tool_set["auth_type"]
    if auth_type != "none":
        headers.update(
            auth_headers(
                db,
                workspace_id,
                {"type": auth_type, "credential_id": tool_set["auth_credential_id"]},
            )
        )
    method = str(op["method"]).upper()
    if method in ("GET", "DELETE") or op.get("body_schema") is None:
        body = None
    elif body in (None, "", {}) and op.get("body_required"):
        raise NodeError("이 도구는 보낼 내용(본문)이 꼭 필요해요. '보낼 내용' 칸을 채워 주세요.")
    res = safe_http.request(method, url, headers=headers, body=body)
    status = int(res.get("status") or 0)
    parsed = res.get("body")
    text = parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False)
    return {
        "status": status,
        "ok": 200 <= status < 300,
        "body": parsed,
        "text": text[:MAX_TEXT],
    }
