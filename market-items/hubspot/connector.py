"""HubSpot 커넥터(비공개 앱 액세스 토큰). api.hubapi.com에만 접속한다."""

from typing import Any

from nodes.spec import NodeError

API = "https://api.hubapi.com"
FIELDS = ("email", "firstname", "lastname", "phone", "company")


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("token") or "")
    if not token:
        raise NodeError("HubSpot 토큰이 비어 있어요. 비공개 앱의 액세스 토큰을 넣어 주세요.")
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    if status == 401:
        raise NodeError("HubSpot 토큰이 올바르지 않아요(401). 연결 정보를 다시 등록하세요.")
    if status == 403:
        raise NodeError(
            "HubSpot 권한이 없어요(403). 비공개 앱에 crm.objects.contacts 범위를 켜세요."
        )
    if status == 409:
        raise NodeError(
            "같은 이메일의 연락처가 이미 있어요(409). 기존 연락처를 쓰거나 이메일을 확인하세요."
        )
    if status == 429:
        raise NodeError("HubSpot 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(
            f"HubSpot에서 {what}하지 못했어요({status}). 값 형식(이메일 등)을 확인하세요."
        )
    body = res.get("body")
    return body if isinstance(body, dict) else {}


def create_contact(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    email = str(params["email"]).strip()
    if "@" not in email:
        raise NodeError("이메일 형식이 맞지 않아요. 예: name@example.com")
    props = {k: str(params[k]) for k in FIELDS if params.get(k)}
    res = net.http(
        "POST",
        API + "/crm/v3/objects/contacts",
        headers=_headers(secrets),
        json={"properties": props},
    )
    data = _check(res, "연락처를 만들")
    return {"id": str(data.get("id", "")), "email": email}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    _check(
        net.http("GET", API + "/crm/v3/objects/contacts?limit=1", headers=_headers(secrets)),
        "연결을 확인",
    )
    return {"message": "HubSpot에 연결됐어요(연락처 읽기 확인)."}
