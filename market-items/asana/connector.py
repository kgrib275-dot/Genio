"""Asana 커넥터(개인 액세스 토큰). app.asana.com에만 접속한다."""

import re
from typing import Any

from nodes.spec import NodeError

API = "https://app.asana.com/api/1.0"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("token") or "")
    if not token:
        raise NodeError("Asana 토큰이 비어 있어요. 연결 정보에 개인 액세스 토큰을 넣어 주세요.")
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    if status in (401, 403):
        raise NodeError(f"Asana 인증에 실패했어요({status}). 토큰과 프로젝트 권한을 확인하세요.")
    if status == 404:
        raise NodeError("Asana 프로젝트를 찾지 못했어요(404). 프로젝트 id를 확인하세요.")
    if status == 429:
        raise NodeError("Asana 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Asana에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    body = res.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


def create_task(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    project = str(params["project_id"]).strip()
    if not re.fullmatch(r"\d{5,25}", project):
        raise NodeError("프로젝트 id는 숫자예요. 프로젝트 주소의 /0/ 다음 숫자를 넣으세요.")
    data: dict[str, Any] = {
        "name": str(params["name"])[:1024],
        "notes": str(params.get("notes") or ""),
        "projects": [project],
    }
    if params.get("due_on"):
        data["due_on"] = str(params["due_on"])
    res = net.http("POST", API + "/tasks", headers=_headers(secrets), json={"data": data})
    out = _check(res, "할 일을 만들")
    return {"gid": str(out.get("gid", "")), "url": str(out.get("permalink_url", ""))}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/users/me", headers=_headers(secrets)), "연결을 확인")
    return {"message": "Asana에 연결됐어요: " + str(data.get("name", ""))}
