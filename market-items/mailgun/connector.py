"""Mailgun 커넥터(메일 보내기). 플랫폼이 넘겨준 net으로만 api.mailgun.net(EU는 api.eu.mailgun.net)에 접속한다."""

import base64
import re
from typing import Any

from nodes.spec import NodeError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]{3,253}$")


def _base(secrets: dict[str, Any]) -> str:
    region = str(secrets.get("region") or "us").strip().lower()
    return "https://api.eu.mailgun.net/v3" if region == "eu" else "https://api.mailgun.net/v3"


def _domain(secrets: dict[str, Any]) -> str:
    domain = str(secrets.get("domain") or "").strip().lower()
    if not DOMAIN_RE.match(domain):
        raise NodeError("Mailgun 도메인 형식이 맞지 않아요. 예: mg.example.com")
    return domain


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    key = str(secrets.get("api_key") or "").strip()
    if not key:
        raise NodeError("Mailgun API 키가 비어 있어요. 연결 정보에 API 키를 넣어 주세요.")
    return {"Authorization": "Basic " + base64.b64encode(f"api:{key}".encode()).decode()}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("Mailgun 인증에 실패했어요. API 키와 지역(US/EU)을 확인하세요.")
    if status == 404:
        raise NodeError("Mailgun에서 도메인을 찾지 못했어요(404). 도메인과 지역(US/EU)을 확인하세요.")
    if status == 429:
        raise NodeError("Mailgun 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Mailgun에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def send_mail(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sender = str(secrets.get("from_email") or "").strip()
    if not sender:
        raise NodeError("보내는 사람 주소가 비어 있어요. 연결 정보의 '보내는 주소'를 넣어 주세요.")
    to = [t.strip() for t in str(params["to"]).replace(";", ",").split(",") if t.strip()]
    if not to or any(not EMAIL_RE.match(t) for t in to):
        raise NodeError("받는 사람 메일 주소 형식이 맞지 않아요. 여러 명은 쉼표로 구분하세요.")
    form = {
        "from": sender,
        "to": ", ".join(to[:50]),
        "subject": str(params["subject"])[:998],
        "text": str(params["text"]),
    }
    if params.get("html"):
        form["html"] = str(params["html"])
    res = net.http(
        "POST", f"{_base(secrets)}/{_domain(secrets)}/messages", headers=_headers(secrets), form=form
    )
    data = _check(res, "메일을 보내")
    return {"sent": True, "message_id": str(data.get("id", "")), "to": to[:50]}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    domain = _domain(secrets)
    data = _check(
        net.http("GET", f"{_base(secrets)}/domains/{domain}", headers=_headers(secrets)),
        "연결을 확인",
    )
    info = data.get("domain") if isinstance(data.get("domain"), dict) else {}
    return {"message": "Mailgun에 연결됐어요: " + str(info.get("name") or domain)}
