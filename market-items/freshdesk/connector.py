"""Freshdesk 커넥터(티켓 만들기·목록). 플랫폼이 넘겨준 net으로만 *.freshdesk.com에 접속한다."""

import base64
import re
from typing import Any

from nodes.spec import NodeError

SUB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _site(secrets: dict[str, Any]) -> str:
    raw = str(secrets.get("domain") or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "").split("/")[0]
    if raw.endswith(".freshdesk.com"):
        raw = raw[: -len(".freshdesk.com")]
    if not SUB_RE.match(raw):
        raise NodeError("Freshdesk 도메인 형식이 맞지 않아요. 예: acme (acme.freshdesk.com의 앞부분)")
    return f"https://{raw}.freshdesk.com"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    key = str(secrets.get("api_key") or "").strip()
    if not key:
        raise NodeError("Freshdesk API 키가 비어 있어요. 연결 정보에 API 키를 넣어 주세요.")
    raw = base64.b64encode(f"{key}:X".encode()).decode()
    return {"Authorization": "Basic " + raw, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> Any:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("Freshdesk 인증에 실패했어요. API 키와 도메인을 확인하세요.")
    if status == 429:
        raise NodeError("Freshdesk 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        reason = ""
        if isinstance(body, dict) and body.get("description"):
            reason = ": " + str(body["description"])[:120]
        raise NodeError(f"Freshdesk에서 {what}하지 못했어요({status}){reason}. 설정 값을 확인하세요.")
    return body


def create_ticket(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    priority = int(params.get("priority") or 1)
    if priority not in (1, 2, 3, 4):
        raise NodeError("우선순위는 1(낮음)~4(긴급) 중에서 고르세요.")
    body = {
        "subject": str(params["subject"])[:250],
        "description": str(params["description"]),
        "email": str(params["email"]),
        "priority": priority,
        "status": 2,
    }
    res = net.http("POST", site + "/api/v2/tickets", headers=_headers(secrets), json=body)
    data = _check(res, "티켓을 만들")
    tid = data.get("id") if isinstance(data, dict) else None
    return {"ticket_id": str(tid or ""), "url": f"{site}/a/tickets/{tid}" if tid else ""}


def list_tickets(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    limit = max(1, min(int(params.get("limit") or 10), 100))
    res = net.http("GET", f"{site}/api/v2/tickets?per_page={limit}", headers=_headers(secrets))
    data = _check(res, "티켓을 읽")
    rows = [
        {
            "id": str(t.get("id", "")),
            "subject": str(t.get("subject", "")),
            "status": str(t.get("status", "")),
        }
        for t in (data if isinstance(data, list) else [])
        if isinstance(t, dict)
    ][:limit]
    return {
        "count": len(rows),
        "results": rows,
        "text": "\n".join(f"#{r['id']} {r['subject']}" for r in rows),
    }


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    data = _check(net.http("GET", site + "/api/v2/agents/me", headers=_headers(secrets)), "연결을 확인")
    contact = data.get("contact") if isinstance(data, dict) and isinstance(data.get("contact"), dict) else {}
    return {"message": "Freshdesk에 연결됐어요: " + str(contact.get("name") or site)}
