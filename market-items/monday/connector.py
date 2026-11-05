"""monday.com 커넥터(보드에 항목 만들기, GraphQL). 플랫폼이 넘겨준 net으로만 api.monday.com에 접속한다."""

import json
from typing import Any

from nodes.spec import NodeError

API = "https://api.monday.com/v2"

CREATE_ITEM = (
    "mutation ($board: ID!, $name: String!, $cols: JSON) "
    "{ create_item(board_id: $board, item_name: $name, column_values: $cols) { id } }"
)


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("api_token") or "").strip()
    if not token:
        raise NodeError("monday.com API 토큰이 비어 있어요. 연결 정보에 개인 API 토큰을 넣어 주세요.")
    return {"Authorization": token, "API-Version": "2024-10", "Content-Type": "application/json"}


def _graphql(net: Any, secrets: dict[str, Any], query: str, variables: dict[str, Any], what: str) -> dict[str, Any]:
    res = net.http("POST", API, headers=_headers(secrets), json={"query": query, "variables": variables})
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("monday.com 인증에 실패했어요. API 토큰을 확인하세요.")
    if status == 429:
        raise NodeError("monday.com 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"monday.com에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    data = body if isinstance(body, dict) else {}
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        raise NodeError(
            f"monday.com이 요청을 거절했어요: {str(first.get('message', ''))[:150]}. 보드 id와 열 값을 확인하세요."
        )
    payload = data.get("data")
    return payload if isinstance(payload, dict) else {}


def create_item(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    board = str(params["board_id"]).strip()
    if not board.isdigit():
        raise NodeError("보드 id는 숫자예요. 보드 주소의 /boards/ 뒤 숫자를 넣어 주세요.")
    columns = params.get("column_values")
    cols = json.dumps(columns, ensure_ascii=False) if isinstance(columns, dict) and columns else None
    data = _graphql(
        net,
        secrets,
        CREATE_ITEM,
        {"board": board, "name": str(params["item_name"])[:255], "cols": cols},
        "항목을 만들",
    )
    item = data.get("create_item") if isinstance(data.get("create_item"), dict) else {}
    return {"item_id": str(item.get("id", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _graphql(net, secrets, "query { me { name } }", {}, "연결을 확인")
    me = data.get("me") if isinstance(data.get("me"), dict) else {}
    return {"message": "monday.com에 연결됐어요: " + str(me.get("name") or "내 계정")}
