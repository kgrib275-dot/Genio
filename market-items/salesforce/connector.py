"""Salesforce 커넥터(액세스 토큰 방식: 리드 만들기, SOQL 조회). 인스턴스 주소는 salesforce.com·force.com만 쓴다."""

import re
from typing import Any
from urllib.parse import quote, urlparse

from nodes.spec import NodeError

API_VERSION = "v60.0"
HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(salesforce|force)\.com$")


def _base(secrets: dict[str, Any]) -> str:
    url = str(secrets.get("instance_url") or "").strip()
    if not url.lower().startswith("https://"):
        url = "https://" + url.replace("http://", "")
    host = (urlparse(url).hostname or "").lower()
    if not HOST_RE.match(host):
        raise NodeError(
            "Salesforce 인스턴스 주소가 올바르지 않아요. 예: https://acme.my.salesforce.com (salesforce.com·force.com 주소만 쓸 수 있어요)"
        )
    return f"https://{host}/services/data/{API_VERSION}"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("access_token") or "").strip()
    if not token:
        raise NodeError("Salesforce 액세스 토큰이 비어 있어요. 연결 정보에 토큰을 넣어 주세요.")
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def _check(res: dict[str, Any], what: str) -> Any:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status == 401:
        raise NodeError("Salesforce 토큰이 만료됐거나 맞지 않아요. 새 액세스 토큰을 연결 정보에 넣어 주세요.")
    if status == 403:
        raise NodeError("Salesforce에서 이 작업을 허용하지 않아요(403). 사용자 권한과 API 사용 설정을 확인하세요.")
    if status >= 400:
        reason = ""
        if isinstance(body, list) and body and isinstance(body[0], dict):
            reason = ": " + str(body[0].get("message", ""))[:120]
        raise NodeError(f"Salesforce에서 {what}하지 못했어요({status}){reason}. 설정 값을 확인하세요.")
    return body


def create_lead(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "LastName": str(params["last_name"])[:80],
        "Company": str(params["company"])[:255],
    }
    for key, sf in (
        ("first_name", "FirstName"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("description", "Description"),
        ("lead_source", "LeadSource"),
    ):
        if params.get(key):
            fields[sf] = str(params[key])
    res = net.http("POST", _base(secrets) + "/sobjects/Lead", headers=_headers(secrets), json=fields)
    data = _check(res, "리드를 만들")
    lead_id = str(data.get("id", "")) if isinstance(data, dict) else ""
    return {"lead_id": lead_id, "success": bool(isinstance(data, dict) and data.get("success"))}


def query(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    soql = " ".join(str(params["soql"]).split())
    if not soql.lower().startswith("select "):
        raise NodeError("조회는 SELECT로 시작하는 SOQL만 쓸 수 있어요. 데이터를 바꾸는 문장은 막혀 있어요.")
    res = net.http("GET", f"{_base(secrets)}/query?q={quote(soql)}", headers=_headers(secrets))
    data = _check(res, "조회하")
    records = data.get("records") if isinstance(data, dict) else []
    rows = [
        {k: v for k, v in r.items() if k != "attributes"}
        for r in (records if isinstance(records, list) else [])
        if isinstance(r, dict)
    ][:200]
    return {
        "count": int(data.get("totalSize", len(rows))) if isinstance(data, dict) else len(rows),
        "records": rows,
        "text": "\n".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in rows[:50]),
    }


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    _check(net.http("GET", _base(secrets) + "/limits", headers=_headers(secrets)), "연결을 확인")
    return {"message": "Salesforce에 연결됐어요."}
