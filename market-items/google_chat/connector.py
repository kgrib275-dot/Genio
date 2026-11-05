"""Google Chat 커넥터(들어오는 웹훅으로 스페이스에 메시지 보내기)."""

import re
from typing import Any

from nodes.spec import NodeError

URL_RE = re.compile(r"^https://chat\.googleapis\.com/v1/spaces/[A-Za-z0-9_-]+/messages\?[^\s]+$")


def _url(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("webhook_url") or "").strip()
    if not URL_RE.match(url):
        raise NodeError(
            "Google Chat 웹훅 주소 형식이 맞지 않아요. 스페이스의 '앱 및 통합 > 웹훅'에서 만든 https://chat.googleapis.com/… 주소를 넣으세요."
        )
    return url


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"text": str(params["text"])[:4000]}
    url = _url(secrets)
    if params.get("thread_key"):
        # 같은 이름의 대화 묶음(스레드)에 이어서 올린다
        url += "&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        body["thread"] = {"threadKey": str(params["thread_key"])[:100]}
    res = net.http("POST", url, json=body)
    status = int(res.get("status", 0))
    if status in (400, 401, 403, 404):
        raise NodeError(
            f"Google Chat이 메시지를 받아 주지 않았어요({status}). 웹훅 주소가 아직 유효한지 확인하세요."
        )
    if status == 429:
        raise NodeError("Google Chat 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Google Chat에 메시지를 보내지 못했어요({status}).")
    data = res.get("body") if isinstance(res.get("body"), dict) else {}
    return {"sent": True, "message_name": str(data.get("name", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    # 웹훅은 보내 보는 것 말고는 확인할 방법이 없어서(스페이스에 글이 올라가요) 형식만 본다
    _url(secrets)
    return {"message": "웹훅 주소 형식이 맞아요. 실제 전송은 흐름에서 시험해 보세요."}
