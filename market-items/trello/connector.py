"""Trello 커넥터(API 키 + 토큰을 OAuth 헤더로 보낸다. 주소에 비밀값을 넣지 않는다)."""

import re
import urllib.parse
from typing import Any

from nodes.spec import NodeError

API = "https://api.trello.com/1"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    key = str(secrets.get("api_key") or "")
    token = str(secrets.get("token") or "")
    if not key or not token:
        raise NodeError("Trello API 키와 토큰을 모두 넣어 주세요. 연결 정보를 다시 등록하세요.")
    return {
        "Authorization": 'OAuth oauth_consumer_key="' + key + '", oauth_token="' + token + '"',
        "Accept": "application/json",
    }


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    if status in (401, 403):
        raise NodeError(
            f"Trello 인증에 실패했어요({status}). API 키·토큰과 보드 권한을 확인하세요."
        )
    if status in (400, 404):
        raise NodeError(f"Trello에서 대상을 찾지 못했어요({status}). 목록(list) id를 확인하세요.")
    if status == 429:
        raise NodeError("Trello 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Trello에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    body = res.get("body")
    return body if isinstance(body, dict) else {}


def create_card(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    list_id = str(params["list_id"]).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{24}", list_id):
        raise NodeError(
            "목록 id는 24자리 영문·숫자예요. 카드 주소 끝에 .json을 붙여 idList를 확인하세요."
        )
    query: dict[str, str] = {
        "idList": list_id,
        "name": str(params["name"])[:16384],
        "desc": str(params.get("desc") or "")[:16384],
    }
    if params.get("due"):
        query["due"] = str(params["due"])
    res = net.http(
        "POST", API + "/cards?" + urllib.parse.urlencode(query), headers=_headers(secrets)
    )
    data = _check(res, "카드를 만들")
    return {
        "id": str(data.get("id", "")),
        "url": str(data.get("shortUrl") or data.get("url") or ""),
    }


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/members/me", headers=_headers(secrets)), "연결을 확인")
    return {"message": "Trello에 연결됐어요: " + str(data.get("username", ""))}
