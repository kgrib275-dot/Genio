"""카카오 알림톡(NHN Cloud Notification - KakaoTalk Bizmessage v2.3)."""

import re
from typing import Any
from urllib.parse import quote

from nodes.spec import NodeError

BASE = "https://api-alimtalk.cloud.toast.com/alimtalk/v2.3/appkeys/"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    return {
        "X-Secret-Key": str(secrets.get("secret_key") or ""),
        "Content-Type": "application/json;charset=UTF-8",
    }


def _header_ok(res: dict[str, Any]) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body") if isinstance(res.get("body"), dict) else {}
    header = body.get("header") or {}
    if status in (401, 403) or header.get("resultCode") in (-1, 401):
        raise NodeError("알림톡 키가 올바르지 않아요. 앱키·시크릿 키를 확인하세요.")
    if status >= 400 or header.get("isSuccessful") is False:
        raise NodeError("알림톡 요청이 실패했어요: " + str(header.get("resultMessage") or status))
    return body


def send(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    to = re.sub(r"[^0-9]", "", str(params["to"]))
    if len(to) < 9:
        raise NodeError("받는 사람 휴대폰 번호가 올바르지 않아요(숫자만 9자리 이상).")
    body = {
        "senderKey": str(secrets.get("sender_key") or ""),
        "templateCode": str(params["template_code"]),
        "recipientList": [
            {
                "recipientNo": to,
                "templateParameter": {
                    str(k): str(v) for k, v in (params.get("parameters") or {}).items()
                },
            }
        ],
    }
    url = BASE + quote(str(secrets.get("app_key") or "")) + "/messages"
    data = _header_ok(net.http("POST", url, headers=_headers(secrets), json=body))
    msg = data.get("message") or {}
    return {"sent": True, "request_id": str(msg.get("requestId", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    url = (
        BASE
        + quote(str(secrets.get("app_key") or ""))
        + "/senders/"
        + quote(str(secrets.get("sender_key") or ""))
    )
    _header_ok(net.http("GET", url, headers=_headers(secrets)))
    return {"message": "알림톡 발신 프로필을 확인했어요."}
