"""두레이(Dooray!) 커넥터(메신저 수신 웹훅)."""

import re
from typing import Any

from nodes.spec import NodeError

URL_RE = re.compile(r"^https://([a-z0-9-]+\.)?dooray\.com/services/[\w/-]+$")


def _url(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("webhook_url") or "").strip()
    if not URL_RE.match(url):
        raise NodeError(
            "두레이 웹훅 주소 형식이 맞지 않아요. 대화방 설정 > 서비스 연동 > 수신 웹훅에서 만든 주소를 넣으세요."
        )
    return url


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "botName": str(params.get("bot_name") or "Genio")[:50],
        "text": str(params["text"])[:10000],
    }
    if params.get("title"):
        body["attachments"] = [
            {"title": str(params["title"]), "text": str(params.get("detail") or "")}
        ]
    res = net.http("POST", _url(secrets), headers={"Content-Type": "application/json"}, json=body)
    status = int(res.get("status", 0))
    if status >= 400:
        raise NodeError(
            f"두레이에 메시지를 보내지 못했어요({status}). 웹훅 주소가 살아 있는지 확인하세요."
        )
    return {"sent": True}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    _url(secrets)
    return {
        "message": "웹훅 주소 형식이 맞아요. 실제 전송은 흐름에서 시험해 보세요(대화방에 글이 올라가요)."
    }
