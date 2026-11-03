"""Google Sheets 커넥터(REST v4). 플랫폼의 net으로만 sheets.googleapis.com에 접속한다."""

from typing import Any
from urllib.parse import quote

from nodes.spec import NodeError

BASE = "https://sheets.googleapis.com/v4/spreadsheets/"


def _auth(secrets: dict[str, Any], write: bool) -> tuple[dict[str, str], str]:
    token = str(secrets.get("access_token") or "")
    key = str(secrets.get("api_key") or "")
    if token:
        return {"Authorization": "Bearer " + token}, ""
    if key and not write:
        return {}, "key=" + quote(key)
    if write:
        raise NodeError("행을 추가하려면 OAuth 액세스 토큰이 필요해요. 연결 정보를 확인하세요.")
    raise NodeError("구글 시트 연결 정보에 토큰이나 API 키가 없어요.")


def _check(res: dict[str, Any]) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("구글 시트 권한이 없어요. 토큰이 만료됐거나 시트 공유 설정을 확인하세요.")
    if status == 404:
        raise NodeError("시트를 찾지 못했어요. 시트 ID와 범위를 확인하세요.")
    if status >= 400 or not isinstance(body, dict):
        raise NodeError("구글 시트 요청이 실패했어요(" + str(status) + ").")
    return body


def read_range(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    headers, query = _auth(secrets, write=False)
    url = BASE + quote(str(params["spreadsheet_id"])) + "/values/" + quote(str(params["range"]))
    if query:
        url += "?" + query
    body = _check(net.http("GET", url, headers=headers))
    values = body.get("values", [])
    text = "\n".join("\t".join(str(c) for c in row) for row in values)
    return {"values": values, "text": text, "rows": len(values)}


def append_rows(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    headers, _ = _auth(secrets, write=True)
    url = (
        BASE
        + quote(str(params["spreadsheet_id"]))
        + "/values/"
        + quote(str(params["range"]))
        + ":append?valueInputOption=USER_ENTERED"
    )
    body = _check(net.http("POST", url, headers=headers, json={"values": params["values"]}))
    updates = body.get("updates", {})
    return {"updated_rows": int(updates.get("updatedRows", 0))}
