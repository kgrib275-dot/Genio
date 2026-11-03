"""Jira Cloud 커넥터(이메일 + API 토큰, 기본 인증). *.atlassian.net에만 접속한다."""

import base64
import re
import urllib.parse
from typing import Any

from nodes.spec import NodeError

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


def _base(secrets: dict[str, Any]) -> str:
    site = str(secrets.get("site") or "").strip().lower()
    site = site.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not re.fullmatch(r"[a-z0-9-]+\.atlassian\.net", site):
        raise NodeError(
            "Jira 주소는 회사이름.atlassian.net 형식이어야 해요. 연결 정보를 확인하세요."
        )
    return "https://" + site


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    email = str(secrets.get("email") or "")
    token = str(secrets.get("api_token") or "")
    if not email or not token:
        raise NodeError("Jira 이메일과 API 토큰을 모두 넣어 주세요. 연결 정보를 다시 등록하세요.")
    raw = base64.b64encode((email + ":" + token).encode("utf-8")).decode("ascii")
    return {
        "Authorization": "Basic " + raw,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError(
            f"Jira 인증에 실패했어요({status}). 이메일·API 토큰과 프로젝트 권한을 확인하세요."
        )
    if status == 404:
        raise NodeError("Jira에서 대상을 찾지 못했어요(404). 프로젝트 키를 확인하세요.")
    if status == 429:
        raise NodeError("Jira 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        detail = ""
        if isinstance(body, dict):
            msgs = list(body.get("errorMessages") or []) + list((body.get("errors") or {}).values())
            detail = " / ".join(str(m) for m in msgs)[:200]
        raise NodeError(
            f"Jira에서 {what}하지 못했어요({status}). {detail or '설정 값을 확인하세요.'}"
        )
    return body if isinstance(body, dict) else {}


def _adf(text: str) -> dict[str, Any]:
    paras = [p for p in text.split("\n") if p.strip()] or [" "]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p[:5000]}]}
            for p in paras[:100]
        ],
    }


def create_issue(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    project = str(params["project_key"]).strip().upper()
    if not KEY_RE.match(project):
        raise NodeError(
            "프로젝트 키는 영문 대문자로 시작해야 해요(예: OPS). 단계 설정을 확인하세요."
        )
    fields: dict[str, Any] = {
        "project": {"key": project},
        "summary": str(params["summary"])[:250],
        "issuetype": {"name": str(params.get("issue_type") or "Task")},
        "description": _adf(str(params.get("description") or "")),
    }
    if params.get("labels"):
        fields["labels"] = [
            s.strip().replace(" ", "_") for s in str(params["labels"]).split(",") if s.strip()
        ]
    base = _base(secrets)
    res = net.http(
        "POST", base + "/rest/api/3/issue", headers=_headers(secrets), json={"fields": fields}
    )
    data = _check(res, "이슈를 만들")
    key = str(data.get("key", ""))
    return {"key": key, "id": str(data.get("id", "")), "url": base + "/browse/" + key}


def search_issues(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    limit = max(1, min(int(params.get("max_results") or 10), 50))
    query = urllib.parse.urlencode(
        {"jql": str(params["jql"]), "maxResults": limit, "fields": "summary,status,assignee"}
    )
    base = _base(secrets)
    res = net.http("GET", base + "/rest/api/3/search/jql?" + query, headers=_headers(secrets))
    data = _check(res, "이슈를 찾")
    issues = []
    for it in data.get("issues") or []:
        f = it.get("fields") or {}
        issues.append(
            {
                "key": str(it.get("key", "")),
                "summary": str(f.get("summary", "")),
                "status": str((f.get("status") or {}).get("name", "")),
            }
        )
    text = "\n".join(f"{i['key']} [{i['status']}] {i['summary']}" for i in issues)
    return {"count": len(issues), "issues": issues, "text": text}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(
        net.http("GET", _base(secrets) + "/rest/api/3/myself", headers=_headers(secrets)),
        "연결을 확인",
    )
    return {"message": "Jira에 연결됐어요: " + str(data.get("displayName") or "")}
