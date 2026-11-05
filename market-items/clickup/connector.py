"""ClickUp 커넥터(작업 만들기). 플랫폼이 넘겨준 net으로만 api.clickup.com에 접속한다."""

import re
from typing import Any

from nodes.spec import NodeError

API = "https://api.clickup.com/api/v2"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,40}$")


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("api_token") or "").strip()
    if not token:
        raise NodeError("ClickUp API 토큰이 비어 있어요. 연결 정보에 개인 API 토큰(pk_…)을 넣어 주세요.")
    # ClickUp은 토큰을 'Bearer' 없이 그대로 보낸다
    return {"Authorization": token, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("ClickUp 인증에 실패했어요. API 토큰을 확인하세요.")
    if status == 404:
        raise NodeError("ClickUp에서 대상을 찾지 못했어요(404). 목록(List) id를 확인하세요.")
    if status == 429:
        raise NodeError("ClickUp 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"ClickUp에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def create_task(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    list_id = str(params["list_id"]).strip()
    if not ID_RE.match(list_id):
        raise NodeError("목록(List) id 형식이 맞지 않아요. ClickUp 목록 주소 끝의 숫자를 넣어 주세요.")
    body: dict[str, Any] = {"name": str(params["name"])[:500]}
    if params.get("description"):
        body["description"] = str(params["description"])
    if params.get("priority"):
        priority = int(params["priority"])
        if priority not in (1, 2, 3, 4):
            raise NodeError("우선순위는 1(긴급)~4(낮음) 중에서 고르세요.")
        body["priority"] = priority
    res = net.http("POST", f"{API}/list/{list_id}/task", headers=_headers(secrets), json=body)
    data = _check(res, "작업을 만들")
    return {"task_id": str(data.get("id", "")), "url": str(data.get("url", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/user", headers=_headers(secrets)), "연결을 확인")
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    return {"message": "ClickUp에 연결됐어요: " + str(user.get("username") or "내 계정")}
