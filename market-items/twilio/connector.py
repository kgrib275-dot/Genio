"""Twilio 커넥터(문자 보내기). 플랫폼이 넘겨준 net으로만 api.twilio.com에 접속한다."""

import base64
import re
from typing import Any

from nodes.spec import NodeError

API = "https://api.twilio.com/2010-04-01"
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _auth(secrets: dict[str, Any]) -> tuple[str, dict[str, str]]:
    sid = str(secrets.get("account_sid") or "").strip()
    token = str(secrets.get("auth_token") or "").strip()
    if not sid.startswith("AC") or not token:
        raise NodeError(
            "Twilio Account SID(AC로 시작)와 Auth Token이 필요해요. 연결 정보를 다시 확인하세요."
        )
    raw = base64.b64encode(f"{sid}:{token}".encode()).decode()
    return sid, {"Authorization": "Basic " + raw}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("Twilio 인증에 실패했어요. Account SID와 Auth Token을 확인하세요.")
    if status == 429:
        raise NodeError("Twilio 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        reason = ""
        if isinstance(body, dict) and body.get("message"):
            reason = ": " + str(body["message"])[:120]
        raise NodeError(f"Twilio에서 {what}하지 못했어요({status}){reason}. 번호와 설정을 확인하세요.")
    return body if isinstance(body, dict) else {}


def send_sms(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sid, headers = _auth(secrets)
    to = str(params["to"]).replace(" ", "").replace("-", "")
    sender = str(params.get("from") or secrets.get("from_number") or "").replace(" ", "")
    if not PHONE_RE.match(to):
        raise NodeError(
            "받는 번호는 +82 같은 국가번호가 붙은 형식이어야 해요. 예: +821012345678"
        )
    form = {"To": to, "Body": str(params["body"])[:1600]}
    if sender.startswith("MG"):
        form["MessagingServiceSid"] = sender
    elif PHONE_RE.match(sender):
        form["From"] = sender
    else:
        raise NodeError(
            "보내는 번호가 없어요. 연결 정보의 보내는 번호(+로 시작)나 메시지 서비스 SID(MG로 시작)를 넣어 주세요."
        )
    res = net.http("POST", f"{API}/Accounts/{sid}/Messages.json", headers=headers, form=form)
    data = _check(res, "문자를 보내")
    return {"message_sid": str(data.get("sid", "")), "status": str(data.get("status", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sid, headers = _auth(secrets)
    data = _check(net.http("GET", f"{API}/Accounts/{sid}.json", headers=headers), "연결을 확인")
    return {"message": "Twilio에 연결됐어요: " + str(data.get("friendly_name") or sid)}
