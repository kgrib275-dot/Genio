"""잔디 커넥트(Incoming Webhook)."""

from typing import Any

from nodes.spec import NodeError

HEADERS = {"Accept": "application/vnd.tosslab.jandi-v2+json", "Content-Type": "application/json"}


def _url(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("webhook_url") or "")
    if not url.startswith("https://wh.jandi.com/"):
        raise NodeError(
            "잔디 웹훅 주소는 https://wh.jandi.com/ 으로 시작해야 해요. 연결 정보를 확인하세요."
        )
    return url


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"body": str(params["body"])}
    if params.get("color"):
        body["connectColor"] = str(params["color"])
    if params.get("title") or params.get("description"):
        body["connectInfo"] = [
            {
                "title": str(params.get("title") or ""),
                "description": str(params.get("description") or ""),
            }
        ]
    res = net.http("POST", _url(secrets), headers=HEADERS, json=body)
    if int(res.get("status", 0)) >= 400:
        raise NodeError(
            "잔디에 메시지를 보내지 못했어요("
            + str(res.get("status"))
            + "). 웹훅 주소를 확인하세요."
        )
    return {"sent": True}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    _url(secrets)
    return {
        "message": "웹훅 주소 형식이 맞아요. 실제 전송은 흐름에서 시험해 보세요(토픽에 글이 올라가요)."
    }
