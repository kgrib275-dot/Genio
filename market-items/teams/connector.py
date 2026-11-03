"""Microsoft Teams 커넥터(Workflows/Incoming Webhook 주소로 적응형 카드 보내기)."""

import re
from typing import Any

from nodes.spec import NodeError

HOST_RE = re.compile(
    r"^https://[a-z0-9.-]+\.(logic\.azure\.com|powerplatform\.com|webhook\.office\.com)(:443)?/"
)


def _url(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("webhook_url") or "").strip()
    if not HOST_RE.match(url):
        raise NodeError(
            "Teams 웹훅 주소 형식이 맞지 않아요. 채널의 '워크플로' > '웹후크 요청 받기'로 만든 주소를 넣으세요."
        )
    return url


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    if params.get("title"):
        body.append(
            {
                "type": "TextBlock",
                "text": str(params["title"]),
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            }
        )
    body.append({"type": "TextBlock", "text": str(params["text"])[:20000], "wrap": True})
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                },
            }
        ],
    }
    res = net.http("POST", _url(secrets), headers={"Content-Type": "application/json"}, json=card)
    status = int(res.get("status", 0))
    if status == 429:
        raise NodeError("Teams 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(
            f"Teams에 메시지를 보내지 못했어요({status}). 웹훅 주소가 살아 있는지 확인하세요."
        )
    return {"sent": True}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    _url(secrets)
    return {
        "message": "웹훅 주소 형식이 맞아요. 실제 전송은 흐름에서 시험해 보세요(채널에 글이 올라가요)."
    }
