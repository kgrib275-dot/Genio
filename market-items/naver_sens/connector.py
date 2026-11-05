"""네이버 클라우드 SENS 커넥터(문자 보내기). 서명(HMAC-SHA256, base64)은 플랫폼이 net으로 대신 만들어 준다."""

import re
from typing import Any

from nodes.spec import NodeError

HOST = "https://sens.apigw.ntruss.com"
PHONE_RE = re.compile(r"^0\d{8,10}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9:_-]{8,80}$")
SMS_MAX_CHARS = 45  # SMS는 90바이트(한글 약 45자)까지, 넘으면 LMS


def _phone(value: Any, what: str) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if digits.startswith("82"):
        digits = "0" + digits[2:]
    if not PHONE_RE.match(digits):
        raise NodeError(f"{what} 번호 형식이 맞지 않아요. 예: 01012345678 (하이픈은 있어도 돼요)")
    return digits


def _keys(secrets: dict[str, Any]) -> tuple[str, str, str]:
    access = str(secrets.get("access_key") or "").strip()
    secret = str(secrets.get("secret_key") or "").strip()
    service = str(secrets.get("service_id") or "").strip()
    if not access or not secret:
        raise NodeError("네이버 클라우드 Access Key와 Secret Key가 필요해요. 연결 정보를 확인하세요.")
    if not SERVICE_RE.match(service):
        raise NodeError("SENS 서비스 ID 형식이 맞지 않아요. 콘솔의 Project > Service ID를 넣어 주세요.")
    return access, secret, service


def _headers(method: str, uri: str, access: str, secret: str, net: Any) -> dict[str, str]:
    timestamp = str(net.now_ms())
    signature = net.sign_hmac_sha256(
        secret, f"{method} {uri}\n{timestamp}\n{access}", encoding="base64"
    )
    return {
        "Content-Type": "application/json; charset=utf-8",
        "x-ncp-apigw-timestamp": timestamp,
        "x-ncp-iam-access-key": access,
        "x-ncp-apigw-signature-v2": signature,
    }


def send_sms(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    access, secret, service = _keys(secrets)
    content = str(params["content"])
    kind = "SMS" if len(content) <= SMS_MAX_CHARS else "LMS"
    body: dict[str, Any] = {
        "type": kind,
        "contentType": "COMM",
        "countryCode": "82",
        "from": _phone(params.get("from") or secrets.get("sender"), "보내는"),
        "content": content[:2000],
        "messages": [{"to": _phone(params["to"], "받는")}],
    }
    if kind == "LMS":
        body["subject"] = str(params.get("subject") or content[:20])[:40]
    uri = f"/sms/v2/services/{service}/messages"
    res = net.http("POST", HOST + uri, headers=_headers("POST", uri, access, secret, net), json=body)
    status = int(res.get("status", 0))
    data = res.get("body") if isinstance(res.get("body"), dict) else {}
    if status in (401, 403):
        raise NodeError("네이버 클라우드 인증에 실패했어요. Access Key·Secret Key와 서비스 ID를 확인하세요.")
    if status == 429:
        raise NodeError("SENS 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        reason = ": " + str(data.get("errorMessage"))[:120] if data.get("errorMessage") else ""
        raise NodeError(f"SENS에서 문자를 보내지 못했어요({status}){reason}. 발신번호 등록을 확인하세요.")
    return {"request_id": str(data.get("requestId", "")), "type": kind, "status": str(data.get("statusName", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    # 문자가 실제로 나가는 호출 말고는 확인 방법이 없어서 연결 정보의 형식만 본다
    _keys(secrets)
    _phone(secrets.get("sender"), "발신")
    return {"message": "연결 정보 형식이 맞아요. 실제 전송은 흐름에서 시험해 보세요."}
