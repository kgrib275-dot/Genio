"""Telegram 커넥터(봇 토큰). 토큰은 주소에 들어가므로 오류 문장에 주소를 넣지 않는다."""

import re
from typing import Any

from nodes.spec import NodeError

TOKEN_RE = re.compile(r"^\d+:[\w-]{20,}$")


def _api(secrets: dict[str, Any], method: str) -> str:
    token = str(secrets.get("bot_token") or "").strip()
    if not TOKEN_RE.match(token):
        raise NodeError("텔레그램 봇 토큰 형식이 맞지 않아요. @BotFather에서 받은 토큰을 넣으세요.")
    return "https://api.telegram.org/bot" + token + "/" + method


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status == 401:
        raise NodeError("텔레그램 봇 토큰이 올바르지 않아요(401). 연결 정보를 다시 등록하세요.")
    if status == 429:
        raise NodeError("텔레그램 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400 or not (isinstance(body, dict) and body.get("ok")):
        desc = str(body.get("description", "")) if isinstance(body, dict) else ""
        if "chat not found" in desc:
            raise NodeError(
                "대화방을 찾지 못했어요. 봇과 먼저 대화를 시작했는지, chat id가 맞는지 확인하세요."
            )
        raise NodeError(
            f"텔레그램에서 {what}하지 못했어요({status}). {desc[:120] or '설정 값을 확인하세요.'}"
        )
    result = body.get("result")
    return result if isinstance(result, dict) else {}


def send_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"chat_id": str(params["chat_id"]), "text": str(params["text"])[:4096]}
    if params.get("parse_mode") in ("HTML", "MarkdownV2"):
        body["parse_mode"] = params["parse_mode"]
    res = net.http(
        "POST",
        _api(secrets, "sendMessage"),
        headers={"Content-Type": "application/json"},
        json=body,
    )
    data = _check(res, "메시지를 보내")
    return {"sent": True, "message_id": int(data.get("message_id") or 0)}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", _api(secrets, "getMe")), "연결을 확인")
    return {"message": "텔레그램 봇에 연결됐어요: @" + str(data.get("username", ""))}
