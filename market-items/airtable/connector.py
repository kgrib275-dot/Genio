"""Airtable 커넥터(개인 액세스 토큰). api.airtable.com에만 접속한다."""

import re
import urllib.parse
from typing import Any

from nodes.spec import NodeError

API = "https://api.airtable.com/v0"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("token") or "")
    if not token:
        raise NodeError("Airtable 토큰이 비어 있어요. 연결 정보에 개인 액세스 토큰을 넣어 주세요.")
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def _table_url(params: dict[str, Any]) -> str:
    base = str(params["base_id"]).strip()
    if not re.fullmatch(r"app[A-Za-z0-9]{14}", base):
        raise NodeError("베이스 id는 app으로 시작하는 17자예요. 베이스 주소에서 확인하세요.")
    table = str(params["table"]).strip()
    if not table:
        raise NodeError("표 이름(또는 tbl로 시작하는 id)을 넣어 주세요.")
    return API + "/" + base + "/" + urllib.parse.quote(table, safe="")


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError(
            f"Airtable 인증에 실패했어요({status}). 토큰의 범위(data.records)와 베이스 권한을 확인하세요."
        )
    if status == 404:
        raise NodeError("Airtable 베이스나 표를 찾지 못했어요(404). 이름을 확인하세요.")
    if status == 422:
        msg = ""
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            msg = str(body["error"].get("message", ""))[:150]
        raise NodeError(
            "Airtable이 값을 받지 않았어요(422). " + (msg or "칸 이름과 값 형식을 확인하세요.")
        )
    if status == 429:
        raise NodeError("Airtable 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Airtable에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def create_record(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    fields = params.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise NodeError('저장할 칸(fields)을 하나 이상 넣어 주세요. 예: {"이름": "{{n1.name}}"}')
    res = net.http(
        "POST",
        _table_url(params),
        headers=_headers(secrets),
        json={"fields": fields, "typecast": True},
    )
    data = _check(res, "줄을 추가")
    return {"id": str(data.get("id", ""))}


def list_records(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    query: dict[str, Any] = {"maxRecords": max(1, min(int(params.get("max_records") or 20), 100))}
    if params.get("formula"):
        query["filterByFormula"] = str(params["formula"])
    res = net.http(
        "GET", _table_url(params) + "?" + urllib.parse.urlencode(query), headers=_headers(secrets)
    )
    data = _check(res, "줄을 읽")
    records = [
        {"id": str(r.get("id", "")), "fields": r.get("fields") or {}}
        for r in data.get("records") or []
        if isinstance(r, dict)
    ]
    return {"count": len(records), "records": records}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/meta/whoami", headers=_headers(secrets)), "연결을 확인")
    return {"message": "Airtable에 연결됐어요(" + str(data.get("id", "")) + ")."}
