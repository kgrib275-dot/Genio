"""솔라피(Solapi) 커넥터(문자·카카오 알림톡). 서명(HMAC-SHA256)은 플랫폼이 net으로 대신 만들어 준다."""

import re
from typing import Any

from nodes.spec import NodeError

API = "https://api.solapi.com"
PHONE_RE = re.compile(r"^0\d{8,10}$")


def _phone(value: Any, what: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if not PHONE_RE.match(digits):
        raise NodeError(f"{what} 번호 형식이 맞지 않아요. 예: 01012345678 (하이픈은 있어도 돼요)")
    return digits


def _headers(secrets: dict[str, Any], net: Any) -> dict[str, str]:
    key = str(secrets.get("api_key") or "").strip()
    secret = str(secrets.get("api_secret") or "").strip()
    if not key or not secret:
        raise NodeError("솔라피 API Key와 API Secret이 필요해요. 연결 정보를 확인하세요.")
    date = net.now_iso()
    salt = net.random_hex(16)
    signature = net.sign_hmac_sha256(secret, date + salt)
    return {
        "Authorization": f"HMAC-SHA256 apiKey={key}, date={date}, salt={salt}, signature={signature}",
        "Content-Type": "application/json",
    }


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("솔라피 인증에 실패했어요. API Key·Secret을 확인하세요.")
    if status == 429:
        raise NodeError("솔라피 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        reason = ""
        if isinstance(body, dict) and body.get("errorMessage"):
            reason = ": " + str(body["errorMessage"])[:120]
        raise NodeError(f"솔라피에서 {what}하지 못했어요({status}){reason}. 번호·발신번호 등록을 확인하세요.")
    return body if isinstance(body, dict) else {}


def _send(message: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    res = net.http(
        "POST", API + "/messages/v4/send", headers=_headers(secrets, net), json={"message": message}
    )
    data = _check(res, "메시지를 보내")
    return {
        "group_id": str(data.get("groupId", "")),
        "message_id": str(data.get("messageId", "")),
        "status": str(data.get("statusMessage") or data.get("statusCode") or ""),
    }


def send_sms(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sender = _phone(params.get("from") or secrets.get("sender"), "보내는")
    message = {
        "to": _phone(params["to"], "받는"),
        "from": sender,
        "text": str(params["text"])[:2000],
    }
    return _send(message, secrets, net)


def send_alimtalk(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    sender = _phone(params.get("from") or secrets.get("sender"), "보내는")
    variables = params.get("variables") if isinstance(params.get("variables"), dict) else {}
    message = {
        "to": _phone(params["to"], "받는"),
        "from": sender,
        "kakaoOptions": {
            "pfId": str(params["pf_id"]),
            "templateId": str(params["template_id"]),
            "variables": {str(k): str(v) for k, v in variables.items()},
        },
    }
    return _send(message, secrets, net)


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(
        net.http("GET", API + "/cash/v1/balance", headers=_headers(secrets, net)), "연결을 확인"
    )
    return {"message": "솔라피에 연결됐어요. 잔액: " + str(data.get("balance", "확인 불가"))}
