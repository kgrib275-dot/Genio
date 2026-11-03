"""Slack 커넥터. 플랫폼이 넘겨준 net으로만 slack.com에 접속한다."""

from typing import Any

from nodes.spec import NodeError

ERRORS = {
    "invalid_auth": "슬랙 토큰이 올바르지 않아요. 연결 정보를 다시 등록하세요.",
    "not_authed": "슬랙 토큰이 없어요. 연결 정보를 다시 등록하세요.",
    "channel_not_found": "채널을 찾지 못했어요. 채널 이름을 확인하세요.",
    "not_in_channel": "봇이 채널에 들어가 있지 않아요. 채널에서 봇을 초대하세요.",
    "is_archived": "보관된 채널이에요. 다른 채널을 고르세요.",
    "msg_too_long": "메시지가 너무 길어요.",
    "ratelimited": "슬랙 요청이 너무 많아요. 잠시 후 다시 시도하세요.",
}


def post_message(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    res = net.http(
        "POST",
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": "Bearer " + str(secrets.get("bot_token", ""))},
        json={"channel": params["channel"], "text": params["text"]},
    )
    body = res.get("body") or {}
    if not isinstance(body, dict) or not body.get("ok"):
        code = body.get("error", "unknown") if isinstance(body, dict) else "unknown"
        raise NodeError(ERRORS.get(code, "슬랙에 메시지를 보내지 못했어요(" + str(code) + ")."), retryable=code == "ratelimited")
    return {"ts": body.get("ts", ""), "channel": body.get("channel", params["channel"])}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    res = net.http(
        "POST",
        "https://slack.com/api/auth.test",
        headers={"Authorization": "Bearer " + str(secrets.get("bot_token", ""))},
    )
    body = res.get("body") or {}
    if not isinstance(body, dict) or not body.get("ok"):
        code = body.get("error", "unknown") if isinstance(body, dict) else "unknown"
        raise NodeError(ERRORS.get(code, "슬랙 연결을 확인하지 못했어요(" + str(code) + ")."))
    return {"message": "슬랙에 연결됐어요: " + str(body.get("team", "")) + " / " + str(body.get("user", ""))}
