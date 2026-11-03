"""카카오워크 커넥터(봇 앱 키). api.kakaowork.com에만 접속한다."""

import urllib.parse
from typing import Any

from nodes.spec import NodeError

API = "https://api.kakaowork.com/v1"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    key = str(secrets.get("app_key") or "")
    if not key:
        raise NodeError(
            "카카오워크 봇 앱 키가 비어 있어요. 관리자 > 봇에서 받은 앱 키를 넣어 주세요."
        )
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status == 401:
        raise NodeError("카카오워크 앱 키가 올바르지 않아요(401). 연결 정보를 다시 등록하세요.")
    if status == 429:
        raise NodeError("카카오워크 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400 or not (isinstance(body, dict) and body.get("success")):
        code = ""
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            code = str(body["error"].get("code", ""))
        if code == "user_not_found":
            raise NodeError("받는 사람을 찾지 못했어요. 카카오워크에 가입한 이메일인지 확인하세요.")
        raise NodeError(
            f"카카오워크에서 {what}하지 못했어요({status} {code}). 설정 값을 확인하세요."
        )
    return body


def send_to_user(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    email = str(params["email"]).strip()
    q = urllib.parse.urlencode({"email": email})
    user = _check(
        net.http("GET", API + "/users.find_by_email?" + q, headers=_headers(secrets)), "사람을 찾"
    )
    user_id = (user.get("user") or {}).get("id")
    conv = _check(
        net.http(
            "POST",
            API + "/conversations.open",
            headers=_headers(secrets),
            json={"user_id": user_id},
        ),
        "대화방을 열",
    )
    conv_id = str((conv.get("conversation") or {}).get("id", ""))
    _check(
        net.http(
            "POST",
            API + "/messages.send",
            headers=_headers(secrets),
            json={"conversation_id": conv_id, "text": str(params["text"])[:4000]},
        ),
        "메시지를 보내",
    )
    return {"sent": True, "conversation_id": conv_id}


def send_to_conversation(
    params: dict[str, Any], secrets: dict[str, Any], net: Any
) -> dict[str, Any]:
    conv_id = str(params["conversation_id"]).strip()
    _check(
        net.http(
            "POST",
            API + "/messages.send",
            headers=_headers(secrets),
            json={"conversation_id": conv_id, "text": str(params["text"])[:4000]},
        ),
        "메시지를 보내",
    )
    return {"sent": True, "conversation_id": conv_id}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/bots.info", headers=_headers(secrets)), "연결을 확인")
    return {
        "message": "카카오워크 봇에 연결됐어요: " + str((data.get("info") or {}).get("name", ""))
    }
