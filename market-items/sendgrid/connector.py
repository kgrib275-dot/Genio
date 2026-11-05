"""SendGrid 커넥터(메일 보내기). 플랫폼이 넘겨준 net으로만 api.sendgrid.com에 접속한다."""

import re
from typing import Any

from nodes.spec import NodeError

API = "https://api.sendgrid.com/v3"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    key = str(secrets.get("api_key") or "").strip()
    if not key:
        raise NodeError("SendGrid API 키가 비어 있어요. 연결 정보에 API 키를 넣어 주세요.")
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> Any:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError(
            "SendGrid 인증에 실패했어요. API 키와 'Mail Send' 권한을 확인하세요."
        )
    if status == 429:
        raise NodeError("SendGrid 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        reason = ""
        errors = body.get("errors") if isinstance(body, dict) else None
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = ": " + str(errors[0].get("message", ""))[:120]
        raise NodeError(f"SendGrid에서 {what}하지 못했어요({status}){reason}. 설정 값을 확인하세요.")
    return body


def send_mail(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sender = str(secrets.get("from_email") or "").strip()
    if not EMAIL_RE.match(sender):
        raise NodeError(
            "보내는 사람 주소가 올바르지 않아요. 연결 정보의 '보내는 주소'를 SendGrid에서 인증한 주소로 넣으세요."
        )
    to = [t.strip() for t in str(params["to"]).replace(";", ",").split(",") if t.strip()]
    if not to or any(not EMAIL_RE.match(t) for t in to):
        raise NodeError("받는 사람 메일 주소 형식이 맞지 않아요. 여러 명은 쉼표로 구분하세요.")
    content = [{"type": "text/plain", "value": str(params["text"])}]
    if params.get("html"):
        content.append({"type": "text/html", "value": str(params["html"])})
    body = {
        "personalizations": [{"to": [{"email": t} for t in to[:50]]}],
        "from": {"email": sender},
        "subject": str(params["subject"])[:998],
        "content": content,
    }
    res = net.http("POST", API + "/mail/send", headers=_headers(secrets), json=body)
    _check(res, "메일을 보내")
    return {"sent": True, "to": to[:50]}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/scopes", headers=_headers(secrets)), "연결을 확인")
    scopes = data.get("scopes") if isinstance(data, dict) else None
    count = len(scopes) if isinstance(scopes, list) else 0
    note = "" if (isinstance(scopes, list) and "mail.send" in scopes) else " (메일 보내기 권한을 확인하세요)"
    return {"message": f"SendGrid에 연결됐어요. 권한 {count}개{note}"}
