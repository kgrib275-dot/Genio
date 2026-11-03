"""v0.6 마켓 확대: 새 번들 검증, 템플릿 그래프 검증(병렬 갈래 포함), 커넥터 요청 형식,
비밀값이 결과·오류에 남지 않는지."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine.validator import ValidationEnv, validate_graph
from api.market.bundle import load_module, read_manifest, validate_bundle
from api.market.service import items_dir
from api.tests.conftest import Team
from nodes import NodeError, registry

CONNECTORS = [
    "notion",
    "jira",
    "teams",
    "discord",
    "telegram",
    "github",
    "trello",
    "asana",
    "airtable",
    "hubspot",
    "linear",
    "dooray",
    "kakaowork",
]
PROMPT_PACKS = [
    "prompts_writing",
    "prompts_meeting",
    "prompts_tone",
    "prompts_translate",
    "prompts_summary",
    "prompts_hr",
    "prompts_marketing",
]
TEMPLATES = [
    "tpl_parallel_translate_summary",
    "tpl_parallel_order_check",
    "tpl_parallel_broadcast",
    "tpl_bug_to_github",
    "tpl_request_to_jira",
    "tpl_meeting_to_notion",
    "tpl_lead_capture",
    "tpl_survey_to_airtable",
    "tpl_feedback_to_linear",
    "tpl_daily_digest_kr",
    "tpl_chat_to_task",
]
NEW = CONNECTORS + PROMPT_PACKS + TEMPLATES


@pytest.mark.parametrize("key", NEW)
def test_bundle_validates(key: str) -> None:
    p = items_dir() / key
    m = read_manifest(p)
    assert m["key"] == key
    validate_bundle(p, m)
    assert (p / "README.md").exists()


def _graph(key: str) -> dict[str, Any]:
    # 설치할 때 채우는 자리 표시(지식베이스 고르기)는 시험용 값으로 바꾼다
    text = (items_dir() / key / "template.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text.replace("{{kb}}", "kb-sample"))
    return data


@pytest.mark.parametrize(
    "key",
    sorted(
        {*TEMPLATES, *(k.name for k in items_dir().iterdir() if (k / "template.json").exists())}
    ),
)
def test_template_graph_validates(key: str) -> None:
    result = validate_graph(_graph(key), ValidationEnv(registry=registry))
    assert result.valid, [e.message for e in result.errors]


@pytest.mark.parametrize("key", TEMPLATES)
def test_template_requires_known_connectors(key: str) -> None:
    m = read_manifest(items_dir() / key)
    used = {n["data"]["connector"] for n in _graph(key)["nodes"] if n["type"] == "connector"}
    assert used <= set((m.get("requires") or {}).get("items") or [])
    for c in used:
        cm = read_manifest(items_dir() / c)
        actions = {a["key"] for a in cm["actions"]}
        node = next(n for n in _graph(key)["nodes"] if n["data"].get("connector") == c)
        assert node["data"]["action"] in actions


def test_parallel_templates_fan_out() -> None:
    parallel = 0
    for key in TEMPLATES:
        edges = _graph(key)["edges"]
        outs: dict[tuple[str, str], int] = {}
        for e in edges:
            k = (e["source"], e.get("sourceHandle") or "")
            outs[k] = outs.get(k, 0) + 1
        if max(outs.values()) > 1:
            parallel += 1
    assert parallel >= 2


def test_catalog_size_and_categories(client: TestClient, team: Team) -> None:
    items = client.get("/api/v1/market/items", headers=team.h("member")).json()
    keys = {i["key"] for i in items}
    assert len(items) >= 50
    assert set(NEW) <= keys
    dev = client.get("/api/v1/market/items?category=개발·업무관리", headers=team.h("member")).json()
    assert {"jira", "github", "linear", "trello", "asana"} <= {i["key"] for i in dev}
    found = client.get("/api/v1/market/items?q=노션", headers=team.h("member")).json()
    assert {"notion", "tpl_meeting_to_notion"} <= {i["key"] for i in found}


# ---------------- 커넥터 요청 형식(가짜 네트워크) ----------------
class FakeNet:
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = responses or []

    def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        form: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json})
        if self.responses:
            return self.responses.pop(0)
        return {"status": 200, "body": {}}


def mod(key: str) -> Any:
    return load_module(items_dir() / key / "connector.py", f"test_{key}")


def ok(body: Any, status: int = 200) -> dict[str, Any]:
    return {"status": status, "body": body}


def test_notion_create_page_request() -> None:
    net = FakeNet([ok({"id": "p1", "url": "https://notion.so/p1"})])
    out = mod("notion").create_page(
        {
            "database_id": "https://www.notion.so/ws/1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d?v=1",
            "title": "주간 회의",
            "content": "첫 문단\n\n둘째 문단",
        },
        {"token": "secret_abc"},
        net,
    )
    c = net.calls[0]
    assert c["method"] == "POST" and c["url"] == "https://api.notion.com/v1/pages"
    assert c["headers"]["Authorization"] == "Bearer secret_abc"
    assert c["json"]["parent"] == {"database_id": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"}
    assert c["json"]["properties"]["Name"]["title"][0]["text"]["content"] == "주간 회의"
    assert len(c["json"]["children"]) == 2
    assert out == {"page_id": "p1", "url": "https://notion.so/p1"}
    with pytest.raises(NodeError, match="어디에 만들지"):
        mod("notion").create_page({"title": "x"}, {"token": "t"}, FakeNet())


def test_jira_issue_and_search() -> None:
    net = FakeNet([ok({"key": "OPS-7", "id": "10"}, 201)])
    out = mod("jira").create_issue(
        {"project_key": "ops", "summary": "프린터 고장", "description": "3층\n복합기"},
        {"site": "https://acme.atlassian.net/", "email": "a@b.c", "api_token": "tok"},
        net,
    )
    c = net.calls[0]
    assert c["url"] == "https://acme.atlassian.net/rest/api/3/issue"
    assert c["headers"]["Authorization"].startswith("Basic ")
    assert c["json"]["fields"]["project"] == {"key": "OPS"}
    assert len(c["json"]["fields"]["description"]["content"]) == 2
    assert out["url"] == "https://acme.atlassian.net/browse/OPS-7"
    net = FakeNet(
        [
            ok(
                {
                    "issues": [
                        {"key": "OPS-1", "fields": {"summary": "A", "status": {"name": "할 일"}}}
                    ]
                }
            )
        ]
    )
    res = mod("jira").search_issues(
        {"jql": 'project = OPS AND status = "To Do"'},
        {"site": "acme.atlassian.net", "email": "a@b.c", "api_token": "tok"},
        net,
    )
    assert "/rest/api/3/search/jql?jql=project" in net.calls[0]["url"]
    assert res["count"] == 1 and "OPS-1 [할 일] A" in res["text"]
    with pytest.raises(NodeError, match=r"atlassian.net"):
        mod("jira").create_issue(
            {"project_key": "OPS", "summary": "x"},
            {"site": "evil.example.com", "email": "a", "api_token": "t"},
            FakeNet(),
        )


def test_messenger_webhooks() -> None:
    teams_url = "https://prod-01.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=x"
    net = FakeNet([ok({}, 202)])
    assert mod("teams").send_message(
        {"text": "안녕", "title": "공지"}, {"webhook_url": teams_url}, net
    )
    card = net.calls[0]["json"]["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and card["body"][1]["text"] == "안녕"
    with pytest.raises(NodeError, match="Teams 웹훅"):
        mod("teams").send_message({"text": "x"}, {"webhook_url": "https://evil.com/x"}, FakeNet())

    dc = "https://discord.com/api/webhooks/123/abc-DEF"
    net = FakeNet([ok({"id": "999"})])
    assert mod("discord").send_message({"content": "배포 완료"}, {"webhook_url": dc}, net) == {
        "sent": True,
        "message_id": "999",
    }
    assert net.calls[0]["url"] == dc + "?wait=true"

    dooray = "https://hook.dooray.com/services/1/2/abc"
    net = FakeNet()
    mod("dooray").send_message({"text": "요약", "title": "제목"}, {"webhook_url": dooray}, net)
    assert net.calls[0]["json"]["botName"] == "Genio"
    assert net.calls[0]["json"]["attachments"][0]["title"] == "제목"


def test_telegram_token_never_in_errors() -> None:
    token = "123456:ABCdefGHIjklMNOpqrSTUvwxYZ12345"  # noqa: S105
    net = FakeNet([ok({"ok": True, "result": {"message_id": 5}})])
    out = mod("telegram").send_message({"chat_id": "42", "text": "hi"}, {"bot_token": token}, net)
    assert out == {"sent": True, "message_id": 5}
    assert net.calls[0]["url"].endswith("/sendMessage")
    bad = FakeNet([ok({"ok": False, "description": "Bad Request: chat not found"}, 400)])
    with pytest.raises(NodeError) as exc:
        mod("telegram").send_message({"chat_id": "1", "text": "x"}, {"bot_token": token}, bad)
    assert token not in exc.value.message and "대화방" in exc.value.message


def test_github_issue_and_list() -> None:
    net = FakeNet([ok({"number": 12, "html_url": "https://github.com/o/r/issues/12"}, 201)])
    out = mod("github").create_issue(
        {"repo": "https://github.com/o/r", "title": "버그", "body": "본문", "labels": "bug, ui"},
        {"token": "ghp_x"},
        net,
    )
    c = net.calls[0]
    assert c["url"] == "https://api.github.com/repos/o/r/issues"
    assert c["json"]["labels"] == ["bug", "ui"] and out["number"] == 12
    net = FakeNet(
        [
            ok(
                [
                    {"number": 1, "title": "A", "state": "open", "html_url": "u1"},
                    {"number": 2, "title": "PR", "state": "open", "pull_request": {}},
                ]
            )
        ]
    )
    res = mod("github").list_issues({"repo": "o/r", "limit": 5}, {"token": "ghp_x"}, net)
    assert res["count"] == 1 and "per_page=5" in net.calls[0]["url"]
    with pytest.raises(NodeError, match="저장소를 찾지"):
        mod("github").list_issues({"repo": "o/r"}, {"token": "t"}, FakeNet([ok({}, 404)]))


def test_trello_asana_airtable_hubspot() -> None:
    net = FakeNet([ok({"id": "c1", "shortUrl": "https://trello.com/c/1"})])
    out = mod("trello").create_card(
        {"list_id": "5f1a2b3c4d5e6f7a8b9c0d1e", "name": "견적서"},
        {"api_key": "KEY", "token": "TOK"},
        net,
    )
    c = net.calls[0]
    assert "KEY" not in c["url"] and "TOK" not in c["url"]
    assert 'oauth_token="TOK"' in c["headers"]["Authorization"]
    assert out["url"] == "https://trello.com/c/1"

    net = FakeNet([ok({"data": {"gid": "7", "permalink_url": "https://app.asana.com/0/1/7"}}, 201)])
    out = mod("asana").create_task(
        {"project_id": "1200000000000", "name": "계약서 검토"}, {"token": "t"}, net
    )
    assert net.calls[0]["json"]["data"]["projects"] == ["1200000000000"] and out["gid"] == "7"

    net = FakeNet([ok({"id": "rec1"})])
    mod("airtable").create_record(
        {"base_id": "appAbCdEfGhIjKlMn", "table": "설문 응답", "fields": {"의견": "좋아요"}},
        {"token": "pat"},
        net,
    )
    assert net.calls[0]["url"].endswith(
        "/appAbCdEfGhIjKlMn/%EC%84%A4%EB%AC%B8%20%EC%9D%91%EB%8B%B5"
    )
    assert net.calls[0]["json"] == {"fields": {"의견": "좋아요"}, "typecast": True}
    with pytest.raises(NodeError, match="베이스 id"):
        mod("airtable").create_record(
            {"base_id": "x", "table": "t", "fields": {"a": 1}}, {"token": "p"}, FakeNet()
        )

    net = FakeNet([ok({"id": "55"}, 201)])
    out = mod("hubspot").create_contact(
        {"email": "kim@example.com", "firstname": "김", "phone": ""}, {"token": "pat-x"}, net
    )
    assert net.calls[0]["json"] == {"properties": {"email": "kim@example.com", "firstname": "김"}}
    with pytest.raises(NodeError, match="이미 있어요"):
        mod("hubspot").create_contact({"email": "a@b.c"}, {"token": "t"}, FakeNet([ok({}, 409)]))


def test_linear_and_kakaowork() -> None:
    net = FakeNet(
        [
            ok(
                {
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {"identifier": "ENG-3", "url": "u"},
                        }
                    }
                }
            )
        ]
    )
    out = mod("linear").create_issue(
        {"team_id": "t1", "title": "개선"}, {"api_key": "lin_api_x"}, net
    )
    c = net.calls[0]
    assert c["headers"]["Authorization"] == "lin_api_x"
    assert c["json"]["variables"]["input"]["teamId"] == "t1" and out["identifier"] == "ENG-3"
    with pytest.raises(NodeError, match="Entity not found"):
        mod("linear").create_issue(
            {"team_id": "x", "title": "y"},
            {"api_key": "k"},
            FakeNet([ok({"errors": [{"message": "Entity not found"}]})]),
        )

    net = FakeNet(
        [
            ok({"success": True, "user": {"id": 77}}),
            ok({"success": True, "conversation": {"id": 900}}),
            ok({"success": True}),
        ]
    )
    out = mod("kakaowork").send_to_user(
        {"email": "kim@corp.kr", "text": "결재 요청"}, {"app_key": "k"}, net
    )
    assert [c["url"].split("/v1/")[1].split("?")[0] for c in net.calls] == [
        "users.find_by_email",
        "conversations.open",
        "messages.send",
    ]
    assert net.calls[2]["json"] == {"conversation_id": "900", "text": "결재 요청"}
    assert out == {"sent": True, "conversation_id": "900"}


def test_connector_runtime_redacts_secrets(client: TestClient, team: Team) -> None:
    """실행 런타임에서 오류가 나도 비밀값은 메시지에 남지 않는다(github 토큰)."""
    from api.connectors.runtime import run_connector
    from api.db import SessionLocal
    from api.engine import safe_http
    from api.tests.conftest import install

    install(client, team, "github")
    secret = "ghp_SUPERSECRET123456"  # noqa: S105
    cred = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "github", "name": "깃허브", "secrets": {"token": secret}},
        headers=team.h("owner"),
    ).json()
    assert secret not in json.dumps(cred)

    def fake_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        raise RuntimeError("boom " + kw["headers"]["Authorization"])

    mp = pytest.MonkeyPatch()
    mp.setattr(safe_http, "request", fake_request)
    try:
        with SessionLocal() as db, pytest.raises(NodeError) as exc:
            run_connector(
                db,
                team.ws,
                connector="github",
                credential_id=cred["id"],
                action="create_issue",
                params={"repo": "o/r", "title": "x"},
            )
    finally:
        mp.undo()
    assert secret not in exc.value.message
