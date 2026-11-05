"""Zendesk 커넥터(티켓 만들기·찾기). 플랫폼이 넘겨준 net으로만 *.zendesk.com에 접속한다."""

import base64
import re
from typing import Any
from urllib.parse import quote

from nodes.spec import NodeError

SUB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PRIORITIES = ("low", "normal", "high", "urgent")


def _site(secrets: dict[str, Any]) -> str:
    raw = str(secrets.get("subdomain") or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "").split("/")[0]
    if raw.endswith(".zendesk.com"):
        raw = raw[: -len(".zendesk.com")]
    if not SUB_RE.match(raw):
        raise NodeError("Zendesk 서브도메인 형식이 맞지 않아요. 예: acme (acme.zendesk.com의 앞부분)")
    return f"https://{raw}.zendesk.com"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    email = str(secrets.get("email") or "").strip()
    token = str(secrets.get("api_token") or "").strip()
    if not email or not token:
        raise NodeError("Zendesk 로그인 이메일과 API 토큰이 필요해요. 연결 정보를 확인하세요.")
    raw = base64.b64encode(f"{email}/token:{token}".encode()).decode()
    return {"Authorization": "Basic " + raw, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("Zendesk 인증에 실패했어요. 이메일·API 토큰과 API 사용 설정을 확인하세요.")
    if status == 429:
        raise NodeError("Zendesk 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Zendesk에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def create_ticket(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    ticket: dict[str, Any] = {
        "subject": str(params["subject"])[:250],
        "comment": {"body": str(params["body"])},
    }
    priority = str(params.get("priority") or "").strip().lower()
    if priority:
        if priority not in PRIORITIES:
            raise NodeError("우선순위는 low·normal·high·urgent 중에서 고르세요.")
        ticket["priority"] = priority
    if params.get("requester_email"):
        ticket["requester"] = {
            "name": str(params.get("requester_name") or params["requester_email"]),
            "email": str(params["requester_email"]),
        }
    tags = [t.strip() for t in str(params.get("tags") or "").split(",") if t.strip()]
    if tags:
        ticket["tags"] = tags[:20]
    res = net.http("POST", site + "/api/v2/tickets.json", headers=_headers(secrets), json={"ticket": ticket})
    data = _check(res, "티켓을 만들")
    made = data.get("ticket") if isinstance(data.get("ticket"), dict) else {}
    tid = made.get("id")
    return {"ticket_id": str(tid or ""), "url": f"{site}/agent/tickets/{tid}" if tid else ""}


def search_tickets(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    limit = max(1, min(int(params.get("limit") or 10), 50))
    query = "type:ticket " + str(params["query"])
    res = net.http(
        "GET",
        f"{site}/api/v2/search.json?query={quote(query)}&per_page={limit}",
        headers=_headers(secrets),
    )
    data = _check(res, "티켓을 찾")
    rows = [
        {
            "id": str(t.get("id", "")),
            "subject": str(t.get("subject", "")),
            "status": str(t.get("status", "")),
            "url": f"{site}/agent/tickets/{t.get('id')}",
        }
        for t in data.get("results") or []
        if isinstance(t, dict)
    ][:limit]
    return {
        "count": len(rows),
        "results": rows,
        "text": "\n".join(f"#{r['id']} [{r['status']}] {r['subject']}" for r in rows),
    }


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    site = _site(secrets)
    data = _check(net.http("GET", site + "/api/v2/users/me.json", headers=_headers(secrets)), "연결을 확인")
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return {"message": "Zendesk에 연결됐어요: " + str(user.get("name") or site)}
