"""Discord 커넥터(채널 웹훅)."""

import re
from typing import Any

from nodes.spec import NodeError

URL_RE = re.compile(r"^https://(discord\.com|discordapp\.com)/api/webhooks/\d+/[\w-]+$")


def _url(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("webhook_url") or "").strip()
    if not URL_RE.match(url):
        raise NodeError(
            "디스코드 웹훅 주소 형식이 맞지 않아요. 채널 설정 > 연동 > 웹후크에서 복사한 주소를 넣으세요."
        )
    return url


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"content": str(params["content"])[:2000]}
    if params.get("username"):
        body["username"] = str(params["username"])[:80]
    res = net.http(
        "POST",
        _url(secrets) + "?wait=true",
        headers={"Content-Type": "application/json"},
        json=body,
    )
    status = int(res.get("status", 0))
    if status == 429:
        raise NodeError("디스코드 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status in (401, 404):
        raise NodeError(
            f"디스코드 웹훅을 찾지 못했어요({status}). 웹훅이 지워지지 않았는지 확인하세요."
        )
    if status >= 400:
        raise NodeError(
            f"디스코드에 메시지를 보내지 못했어요({status}). 내용 길이(2,000자)를 확인하세요."
        )
    data = res.get("body")
    return {"sent": True, "message_id": str(data.get("id", "")) if isinstance(data, dict) else ""}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    res = net.http("GET", _url(secrets))
    status = int(res.get("status", 0))
    if status >= 400:
        raise NodeError(
            f"디스코드 웹훅을 확인하지 못했어요({status}). 주소를 다시 복사해 넣으세요."
        )
    data = res.get("body")
    name = str(data.get("name", "")) if isinstance(data, dict) else ""
    return {"message": "디스코드 웹훅에 연결됐어요: " + name}
