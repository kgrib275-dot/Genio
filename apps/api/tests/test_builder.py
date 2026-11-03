"""빌더 녹화형 테스트: 데모 시나리오 3개(설계서 §12)의 툴 호출 시퀀스 스냅샷.

LLM 대신 스크립트(FakeAdapter)가 툴을 부르고, 플랫폼이 이를 처리한 결과(툴 성공 여부, 그래프 변경,
SSE 이벤트 종류, 최종 그래프, 테스트 실행 결과)를 스냅샷과 비교한다.
스냅샷을 새로 만들려면 UPDATE_SNAPSHOTS=1 로 실행한다.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.connectors.runtime import ConnectorNet
from api.engine import safe_http
from api.tests.conftest import Team, add_llm, install
from api.tests.fakes import FakeAdapter, last_tool_result, text_turn, tool_turn
from nodes import NodeError

SNAP_DIR = Path(__file__).with_name("snapshots")


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for frame in body.split("\n\n"):
        name, data = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


def send(
    client: TestClient,
    team: Team,
    session_id: str,
    content: str,
    event: dict[str, Any] | None = None,
) -> list[tuple[str, Any]]:
    body: dict[str, Any] = {"content": content}
    if event:
        body["event"] = event
    with client.stream(
        "POST",
        f"/api/v1/builder/sessions/{session_id}/messages",
        json=body,
        headers=team.h("builder"),
    ) as res:
        assert res.status_code == 200
        return parse_sse("".join(res.iter_text()))


def turn_record(events: list[tuple[str, Any]]) -> dict[str, Any]:
    done = next(d for n, d in events if n == "done")
    rec = done["graph_patch"] or {}
    return {
        "events": [n for n, _ in events if n not in ("text",)],
        "tools": [(c["name"], c["ok"]) for c in rec.get("tool_calls", [])],
        "ops": [o["op"] for o in rec.get("ops", [])],
        "ask_user": rec.get("ask_user"),
        "market_suggestion": (rec.get("market_suggestion") or {}).get("item", {}).get("key"),
        "test_status": (rec.get("test_result") or {}).get("status"),
    }


def graph_shape(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "nodes": sorted(f"{n['id']}:{n['type']}" for n in graph["nodes"]),
        "edges": sorted(
            f"{e['source']}{'(' + e['sourceHandle'] + ')' if e.get('sourceHandle') else ''}->{e['target']}"
            for e in graph["edges"]
        ),
    }


def check_snapshot(name: str, data: Any) -> None:
    SNAP_DIR.mkdir(exist_ok=True)
    path = SNAP_DIR / f"{name}.json"
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(text + "\n", encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(text), (
        f"스냅샷 불일치: {path.name}"
    )


def new_session(client: TestClient, team: Team, name: str) -> tuple[str, str]:
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": name, "type": "chat"},
        headers=team.h("builder"),
    ).json()["id"]
    session_id = client.post(
        f"/api/v1/apps/{app_id}/builder/sessions", headers=team.h("builder")
    ).json()["id"]
    return app_id, session_id


def add_credential(client: TestClient, team: Team, key: str, secrets: dict[str, str]) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": key, "name": f"{key} 연결", "secrets": secrets},
        headers=team.h("admin"),
    )
    assert res.status_code == 200, res.text
    cred_id: str = res.json()["id"]
    return cred_id


@pytest.fixture
def fake_net(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        sent.append({"method": method, "url": url, "body": kw.get("body")})
        if "slack.com" in url:
            return {
                "status": 200,
                "body": {"ok": True, "ts": "1700.01", "channel": "C1"},
                "headers": {},
            }
        if "sheets.googleapis.com" in url:
            rows = [["이름", "이번 주 한 일"], ["김", "API 설계"], ["박", "캔버스 개발"]]
            return {"status": 200, "body": {"values": rows}, "headers": {}}
        raise NodeError("예상하지 못한 호출")

    def fake_mail(self: ConnectorNet, **kw: Any) -> dict[str, Any]:
        sent.append({"mail": kw["to"], "subject": kw["subject"]})
        return {"sent": True, "to": kw["to"]}

    monkeypatch.setattr(safe_http, "request", fake_request)
    monkeypatch.setattr(ConnectorNet, "send_mail", fake_mail)
    return sent


# ---------------------------------------------------------------------------
def test_scenario1_inquiry_to_slack(
    client: TestClient, team: Team, fake_llm: FakeAdapter, fake_net: list[dict[str, Any]]
) -> None:
    add_llm(client, team)
    app_id, sid = new_session(client, team, "문의 분류")

    # 1) 요청 → 슬랙 커넥터가 없어 마켓 제안
    fake_llm.script = [
        tool_turn("먼저 쓸 수 있는 기능을 확인할게요.", ("list_available_nodes", {})),
        tool_turn(
            "슬랙 커넥터가 아직 없어요. 설치할까요?",
            (
                "suggest_market_item",
                {
                    "type": "connector",
                    "reason": "슬랙 채널로 문의를 보내려면 Slack 커넥터가 필요해요",
                    "item_key": "slack",
                },
            ),
        ),
    ]
    t1 = turn_record(send(client, team, sid, "문의 메일을 분류해서 담당자 슬랙으로 보내 줘"))

    # 2) 사용자가 설치 → 흐름 구성 → 채널 질문
    install(client, team, "slack")
    add_credential(client, team, "slack", {"bot_token": "xoxb-secret-token-9999"})

    def build(messages: list[Any]) -> Any:
        cred = last_tool_result(messages, "list_available_nodes")["credentials"][0]["id"]
        return tool_turn(
            "분류 → 분기 → 슬랙 전송 순서로 만들게요.",
            (
                "update_node",
                {
                    "id": "n1",
                    "data": {
                        "label": "문의 입력",
                        "fields": [
                            {
                                "key": "message",
                                "label": "문의 내용",
                                "type": "text",
                                "required": True,
                            }
                        ],
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "llm",
                    "after": "n1",
                    "data": {
                        "label": "문의 분류",
                        "provider": "default",
                        "system": "billing/tech/other 중 하나로 분류",
                        "prompt": "{{n1.message}}",
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string", "enum": ["billing", "tech", "other"]}
                            },
                            "required": ["category"],
                        },
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "condition",
                    "after": "n3",
                    "data": {
                        "label": "분류별",
                        "cases": [
                            {"id": "billing", "when": "{{n3.category}} == 'billing'"},
                            {"id": "tech", "when": "{{n3.category}} == 'tech'"},
                        ],
                        "else": "other",
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "connector",
                    "after": "n4",
                    "handle": "billing",
                    "data": {
                        "label": "빌링 채널",
                        "connector": "slack",
                        "action": "post_message",
                        "credential_id": cred,
                        "params": {"channel": "#?", "text": "{{n1.message}}"},
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "connector",
                    "after": "n4",
                    "handle": "tech",
                    "data": {
                        "label": "기술 채널",
                        "connector": "slack",
                        "action": "post_message",
                        "credential_id": cred,
                        "params": {"channel": "#?", "text": "{{n1.message}}"},
                    },
                },
            ),
            ("connect", {"source": "n5", "target": "n2"}),
            ("connect", {"source": "n6", "target": "n2"}),
            ("connect", {"source": "n4", "target": "n2", "handle": "other"}),
            ("update_node", {"id": "n2", "data": {"template": "분류: {{n3.category}}"}}),
        )(messages)

    fake_llm.script = [
        tool_turn("설치한 슬랙을 확인할게요.", ("list_available_nodes", {})),
        build,
        tool_turn(
            "분류 기준을 billing/tech/other로 잡았어요. 채널은 어디로 보낼까요?",
            (
                "ask_user",
                {
                    "question": "빌링·기술 문의를 각각 어느 채널로 보낼까요?",
                    "options": ["#billing / #tech", "#support 하나로"],
                },
            ),
        ),
    ]
    t2 = turn_record(send(client, team, sid, "응", {"type": "installed", "item_key": "slack"}))

    # 3) 채널 답변 → 수정 → 검증 → 테스트 실행
    fake_llm.script = [
        tool_turn(
            "채널을 바꾸고 검증할게요.",
            (
                "update_node",
                {
                    "id": "n5",
                    "data": {"params": {"channel": "#billing", "text": "[결제] {{n1.message}}"}},
                },
            ),
            (
                "update_node",
                {
                    "id": "n6",
                    "data": {"params": {"channel": "#tech", "text": "[기술] {{n1.message}}"}},
                },
            ),
            ("validate", {}),
        ),
        tool_turn(
            "검증을 통과했어요. 테스트해 볼게요.",
            ("run_test", {"input": {"message": "결제가 두 번 됐어요"}}),
        ),
        text_turn("테스트 결과 billing으로 분류돼 #billing에 전송됐어요. 배포할까요?"),
    ]
    events3 = send(client, team, sid, "빌링은 #billing, 기술은 #tech")
    t3 = turn_record(events3)

    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    check_snapshot("builder_scenario1", {"turns": [t1, t2, t3], "graph": graph_shape(graph)})

    assert t1["market_suggestion"] == "slack"
    assert t2["ask_user"]["options"] == ["#billing / #tech", "#support 하나로"]
    assert t3["test_status"] == "succeeded"
    slack_calls = [c for c in fake_net if "slack.com" in c.get("url", "")]
    assert slack_calls and slack_calls[0]["body"]["channel"] == "#billing"
    assert "xoxb-secret" not in json.dumps(events3, ensure_ascii=False)
    # 이전 차례 맥락이 다음 차례에 텍스트로 전달됐는지
    last_chat = [c for c in fake_llm.calls if c["kind"] == "chat"][-1]
    assert "n5" in last_chat["system"] and "[connector]" in last_chat["system"]


# ---------------------------------------------------------------------------
REGULATION = """제1조(연차) 입사 1년이 지나면 연차 15일이 생긴다. 3년마다 1일씩 늘어난다.

제2조(재택근무) 재택근무는 주 2회까지 가능하며 팀장 승인이 필요하다.

제3조(경조사) 본인 결혼 시 경조 휴가 5일과 축하금 50만 원을 지급한다."""


def test_scenario2_faq_bot_share_link(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    add_llm(client, team, provider="openai", model="gpt-4o-mini")  # 임베딩용
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "사내 규정", "chunk_size": 200},
        headers=team.h("builder"),
    ).json()
    up = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("사내규정.txt", REGULATION.encode("utf-8"), "text/plain")},
        headers=team.h("builder"),
    )
    assert up.status_code == 200 and up.json()["status"] == "ready", up.text
    app_id, sid = new_session(client, team, "규정 FAQ")

    def build(messages: list[Any]) -> Any:
        kb_id = last_tool_result(messages, "list_available_nodes")["knowledge_bases"][0]["id"]
        return tool_turn(
            "문서 검색 → 답변 작성 순서로 만들게요.",
            (
                "add_node",
                {
                    "type": "knowledge_search",
                    "after": "n1",
                    "data": {
                        "label": "규정 검색",
                        "kb_id": kb_id,
                        "query": "{{n1.message}}",
                        "top_k": 2,
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "llm",
                    "after": "n3",
                    "data": {
                        "label": "답변",
                        "provider": "default",
                        "system": "자료로만 답하세요",
                        "prompt": "자료:\n{{n3.context}}\n\n질문: {{n1.message}}",
                    },
                },
            ),
            ("update_node", {"id": "n2", "data": {"label": "답변", "template": "{{n4.text}}"}}),
            ("validate", {}),
        )(messages)

    fake_llm.script = [
        tool_turn("쓸 수 있는 지식베이스를 볼게요.", ("list_available_nodes", {})),
        build,
        tool_turn("테스트해 볼게요.", ("run_test", {"input": {"message": "연차는 며칠이에요?"}})),
        text_turn("검증과 테스트를 통과했어요. 공유 링크로 배포할 수 있어요."),
    ]
    t1 = turn_record(send(client, team, sid, "사내 규정 문서로 FAQ 챗봇 만들어 줘"))
    assert t1["test_status"] == "succeeded"

    # 버전 저장 → 공유 링크 배포(워크스페이스 멤버) → member 계정으로 질문
    assert (
        client.post(
            f"/api/v1/apps/{app_id}/versions", json={"note": "첫 배포"}, headers=team.h("builder")
        ).status_code
        == 201
    )
    dep = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "workspace"},
        headers=team.h("builder"),
    )
    assert dep.status_code == 201, dep.text
    token = dep.json()["public_token"]
    assert dep.json()["share_url"].endswith(f"/share/{token}")
    info = client.get(f"/api/v1/public/apps/{token}", headers=team.h("member")).json()
    assert info["can_use"] and info["input_fields"][0]["key"] == "message"
    with client.stream(
        "POST",
        f"/api/v1/public/apps/{token}/chat",
        json={"message": "연차는 며칠이에요?"},
        headers=team.h("member"),
    ) as res:
        events = parse_sse("".join(res.iter_text()))
    answer = next(d for n, d in events if n == "answer")["text"]
    assert "연차 15일" in answer
    cites = next(d for n, d in events if n == "citations")
    assert cites[0]["filename"] == "사내규정.txt" and cites[0]["index"] == 1
    assert (
        client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=team.h("member")).json()[0][
            "status"
        ]
        == "published"
    )

    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    check_snapshot(
        "builder_scenario2",
        {"turns": [t1], "graph": graph_shape(graph), "chat_events": [n for n, _ in events]},
    )


# ---------------------------------------------------------------------------
def test_scenario3_weekly_report_approval_mail(
    client: TestClient, team: Team, fake_llm: FakeAdapter, fake_net: list[dict[str, Any]]
) -> None:
    add_llm(client, team)
    app_id, sid = new_session(client, team, "주간 보고")

    fake_llm.script = [
        tool_turn("필요한 서비스를 확인할게요.", ("list_available_nodes", {})),
        tool_turn(
            "구글시트 커넥터가 필요해요.",
            (
                "suggest_market_item",
                {"type": "connector", "reason": "구글시트에서 주간 업무 표를 읽어야 해요"},
            ),
        ),
    ]
    t1 = turn_record(
        send(
            client,
            team,
            sid,
            "주간 보고 초안 만들어 줘. 구글시트 읽어서 요약하고 승인 받으면 메일 보내 줘",
        )
    )
    assert t1["market_suggestion"] == "google_sheets"
    install(client, team, "google_sheets")

    fake_llm.script = [
        tool_turn(
            "메일 발송도 필요해요.",
            (
                "suggest_market_item",
                {"type": "connector", "reason": "승인 뒤 메일을 보내야 해요", "item_key": "email"},
            ),
        ),
    ]
    t2 = turn_record(
        send(client, team, sid, "설치했어", {"type": "installed", "item_key": "google_sheets"})
    )
    install(client, team, "email")
    add_credential(client, team, "google_sheets", {"api_key": "AIza-test-key-0000"})
    add_credential(
        client,
        team,
        "email",
        {
            "host": "smtp.example.com",
            "port": "587",
            "username": "bot",
            "password": "pw-secret-77",
            "sender": "bot@example.com",
        },
    )

    def build(messages: list[Any]) -> Any:
        creds = {
            c["connector"]: c["id"]
            for c in last_tool_result(messages, "list_available_nodes")["credentials"]
        }
        return tool_turn(
            "시트 읽기 → 요약 → 승인 → 메일 순서로 만들게요.",
            (
                "update_node",
                {
                    "id": "n1",
                    "data": {
                        "fields": [
                            {"key": "message", "label": "요청", "required": False},
                            {"key": "to", "label": "받는 사람", "required": True},
                        ]
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "connector",
                    "after": "n1",
                    "data": {
                        "label": "시트 읽기",
                        "connector": "google_sheets",
                        "action": "read_range",
                        "credential_id": creds["google_sheets"],
                        "params": {"spreadsheet_id": "sheet123", "range": "주간!A1:B20"},
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "llm",
                    "after": "n3",
                    "data": {
                        "label": "보고서 요약",
                        "provider": "default",
                        "prompt": "{{n3.text}}",
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "subject": {"type": "string"},
                                "body": {"type": "string"},
                            },
                        },
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "approval",
                    "after": "n4",
                    "data": {
                        "label": "발송 승인",
                        "message": "이 보고서를 보낼까요?\n{{n4.subject}}",
                    },
                },
            ),
            (
                "add_node",
                {
                    "type": "connector",
                    "after": "n5",
                    "data": {
                        "label": "메일 발송",
                        "connector": "email",
                        "action": "send_email",
                        "credential_id": creds["email"],
                        "params": {
                            "to": "{{n1.to}}",
                            "subject": "{{n4.subject}}",
                            "body": "{{n4.body}}",
                        },
                    },
                },
            ),
            ("update_node", {"id": "n2", "data": {"template": "보냄: {{n4.subject}}"}}),
            ("validate", {}),
        )(messages)

    fake_llm.script = [
        tool_turn("이제 흐름을 만들게요.", ("list_available_nodes", {})),
        build,
        tool_turn("테스트할게요.", ("run_test", {"input": {"to": "team@example.com"}})),
        text_turn("테스트가 승인 단계에서 멈췄어요. 실행 기록에서 승인하면 메일이 나가요."),
    ]
    t3 = turn_record(
        send(client, team, sid, "둘 다 설치했어", {"type": "installed", "item_key": "email"})
    )
    assert t3["test_status"] == "waiting_approval"

    runs = client.get(f"/api/v1/apps/{app_id}/runs", headers=team.h("operator")).json()
    run_id = runs[0]["id"]
    done = client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"approved": True, "comment": "확인"},
        headers=team.h("operator"),
    ).json()
    assert done["status"] == "succeeded", done["error"]
    mails = [c for c in fake_net if "mail" in c]
    assert mails == [
        {"mail": ["team@example.com"], "subject": done["steps"][2]["output"]["subject"]}
    ]

    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    check_snapshot(
        "builder_scenario3",
        {"turns": [t1, t2, t3], "graph": graph_shape(graph), "final_status": done["status"]},
    )


# ---------------------------------------------------------------------------
def test_builder_without_llm_explains_fix(client: TestClient, team: Team) -> None:
    _, sid = new_session(client, team, "키 없음")
    events = send(client, team, sid, "안녕")
    names = [n for n, _ in events]
    assert names[0] == "user_message" and names[-1] == "done"
    err = next(d for n, d in events if n == "error")
    assert err["message"] == "등록된 AI 연결이 없어요."


def test_tool_errors_reported_to_model(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    _, sid = new_session(client, team, "오류")
    fake_llm.script = [
        tool_turn(
            "",
            ("add_node", {"type": "teleport", "data": {}}),
            ("connect", {"source": "n1", "target": "n1"}),
            ("remove_node", {"id": "zz"}),
        ),
        text_turn("다 만들었어요. 완료!"),
    ]
    events = send(client, team, sid, "아무거나")
    results = [d for n, d in events if n == "tool_result"]
    assert [r["ok"] for r in results] == [False, False, False]
    # 검증 통과 전 '완료'라고 하면 자동 검증 결과를 덧붙인다(그래프 변경이 없으면 생략)
    done = next(d for n, d in events if n == "done")
    assert "검증" not in done["content"]


def test_done_claim_without_validation_gets_note(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    _, sid = new_session(client, team, "검증")
    fake_llm.script = [
        tool_turn(
            "", ("add_node", {"type": "llm", "after": "n1", "data": {"label": "빈 프롬프트"}})
        ),
        text_turn("완료했어요!"),
    ]
    events = send(client, team, sid, "AI 노드 하나 넣어 줘")
    done = next(d for n, d in events if n == "done")
    assert "아직 검증을 통과하지 못했어요" in done["content"]
