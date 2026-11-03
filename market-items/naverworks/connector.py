"""네이버웍스 Bot API v2.0."""

from typing import Any
from urllib.parse import quote

from nodes.spec import NodeError

BASE = "https://www.worksapis.com/v1.0/bots/"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": "Bearer " + str(secrets.get("access_token") or "")}


def _check(res: dict[str, Any], what: str) -> None:
    status = int(res.get("status", 0))
    if status == 401:
        raise NodeError(
            "네이버웍스 토큰이 만료됐거나 올바르지 않아요. 연결 정보를 다시 등록하세요."
        )
    if status == 404:
        raise NodeError("봇이나 받는 곳을 찾지 못했어요. 봇 ID와 사용자·채널 ID를 확인하세요.")
    if status >= 400:
        raise NodeError(what + " 실패(" + str(status) + ").")


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    bot = quote(str(secrets.get("bot_id") or ""))
    kind = "channels" if params.get("target_type") == "channel" else "users"
    url = BASE + bot + "/" + kind + "/" + quote(str(params["target_id"])) + "/messages"
    res = net.http(
        "POST",
        url,
        headers=_headers(secrets),
        json={"content": {"type": "text", "text": str(params["text"])}},
    )
    _check(res, "네이버웍스 메시지 보내기")
    return {"sent": True}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    res = net.http("GET", BASE + quote(str(secrets.get("bot_id") or "")), headers=_headers(secrets))
    _check(res, "네이버웍스 봇 확인")
    body = res.get("body") or {}
    name = body.get("botName", "") if isinstance(body, dict) else ""
    return {"message": "네이버웍스 봇에 연결됐어요" + (": " + str(name) if name else ".")}
