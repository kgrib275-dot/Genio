"""Linear 커넥터(개인 API 키, GraphQL). api.linear.app에만 접속한다."""

from typing import Any

from nodes.spec import NodeError

API = "https://api.linear.app/graphql"


def _gql(
    secrets: dict[str, Any], net: Any, query: str, variables: dict[str, Any], what: str
) -> dict[str, Any]:
    key = str(secrets.get("api_key") or "")
    if not key:
        raise NodeError("Linear API 키가 비어 있어요. 설정 > API에서 만든 개인 키를 넣어 주세요.")
    res = net.http(
        "POST",
        API,
        headers={"Authorization": key, "Content-Type": "application/json"},
        json={"query": query, "variables": variables},
    )
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError(f"Linear 인증에 실패했어요({status}). API 키를 확인하세요.")
    if status == 429:
        raise NodeError("Linear 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if isinstance(body, dict) and body.get("errors"):
        first = body["errors"][0] if isinstance(body["errors"], list) and body["errors"] else {}
        msg = str(first.get("message", "")) if isinstance(first, dict) else ""
        raise NodeError(f"Linear에서 {what}하지 못했어요. {msg[:150] or '설정 값을 확인하세요.'}")
    if status >= 400 or not isinstance(body, dict):
        raise NodeError(f"Linear에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    data = body.get("data")
    return data if isinstance(data, dict) else {}


CREATE = """mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}"""


def create_issue(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    inp: dict[str, Any] = {
        "teamId": str(params["team_id"]).strip(),
        "title": str(params["title"])[:255],
        "description": str(params.get("description") or ""),
    }
    if params.get("priority") not in (None, ""):
        inp["priority"] = max(0, min(int(params["priority"]), 4))
    data = _gql(secrets, net, CREATE, {"input": inp}, "이슈를 만들")
    issue = (data.get("issueCreate") or {}).get("issue") or {}
    return {"identifier": str(issue.get("identifier", "")), "url": str(issue.get("url", ""))}


def list_teams(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _gql(secrets, net, "query { teams { nodes { id key name } } }", {}, "팀 목록을 읽")
    teams = [
        {"id": str(t.get("id", "")), "key": str(t.get("key", "")), "name": str(t.get("name", ""))}
        for t in ((data.get("teams") or {}).get("nodes") or [])
        if isinstance(t, dict)
    ]
    return {
        "count": len(teams),
        "teams": teams,
        "text": "\n".join(f"{t['key']} {t['name']} ({t['id']})" for t in teams),
    }


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _gql(secrets, net, "query { viewer { name } }", {}, "연결을 확인")
    return {"message": "Linear에 연결됐어요: " + str((data.get("viewer") or {}).get("name", ""))}
