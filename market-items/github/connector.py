"""GitHub 커넥터(개인 액세스 토큰). api.github.com에만 접속한다."""

import re
import urllib.parse
from typing import Any

from nodes.spec import NodeError

API = "https://api.github.com"
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("token") or "")
    if not token:
        raise NodeError("GitHub 토큰이 비어 있어요. 연결 정보에 개인 액세스 토큰을 넣어 주세요.")
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Genio",
    }


def _repo(value: Any) -> str:
    repo = str(value or "").strip().removeprefix("https://github.com/").strip("/")
    if not REPO_RE.match(repo):
        raise NodeError("저장소는 '소유자/이름' 형식으로 넣어 주세요(예: my-org/my-repo).")
    return repo


def _check(res: dict[str, Any], what: str) -> Any:
    status = int(res.get("status", 0))
    if status == 401:
        raise NodeError("GitHub 토큰이 올바르지 않아요(401). 연결 정보를 다시 등록하세요.")
    if status == 403:
        raise NodeError(
            "GitHub 권한이 없거나 요청 한도를 넘었어요(403). 토큰 권한(Issues)을 확인하세요."
        )
    if status == 404:
        raise NodeError("저장소를 찾지 못했어요(404). 이름과 토큰의 저장소 접근 권한을 확인하세요.")
    if status == 410:
        raise NodeError(
            "이 저장소는 이슈 기능이 꺼져 있어요(410). 저장소 설정에서 Issues를 켜세요."
        )
    if status >= 400:
        raise NodeError(f"GitHub에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return res.get("body")


def create_issue(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": str(params["title"])[:256],
        "body": str(params.get("body") or ""),
    }
    if params.get("labels"):
        body["labels"] = [s.strip() for s in str(params["labels"]).split(",") if s.strip()]
    res = net.http(
        "POST",
        API + "/repos/" + _repo(params["repo"]) + "/issues",
        headers=_headers(secrets),
        json=body,
    )
    data = _check(res, "이슈를 만들")
    data = data if isinstance(data, dict) else {}
    return {"number": int(data.get("number") or 0), "url": str(data.get("html_url", ""))}


def list_issues(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    state = str(params.get("state") or "open")
    if state not in ("open", "closed", "all"):
        state = "open"
    limit = max(1, min(int(params.get("limit") or 10), 50))
    query = urllib.parse.urlencode({"state": state, "per_page": limit})
    res = net.http(
        "GET",
        API + "/repos/" + _repo(params["repo"]) + "/issues?" + query,
        headers=_headers(secrets),
    )
    data = _check(res, "이슈 목록을 읽")
    issues = [
        {
            "number": int(i.get("number") or 0),
            "title": str(i.get("title", "")),
            "state": str(i.get("state", "")),
            "url": str(i.get("html_url", "")),
        }
        for i in (data if isinstance(data, list) else [])
        if isinstance(i, dict) and "pull_request" not in i
    ]
    text = "\n".join(f"#{i['number']} {i['title']}" for i in issues)
    return {"count": len(issues), "issues": issues, "text": text}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/user", headers=_headers(secrets)), "연결을 확인")
    login = str(data.get("login", "")) if isinstance(data, dict) else ""
    return {"message": "GitHub에 연결됐어요: " + login}
