"""데모 AI: 키 없이 훑어보고, 진짜 키를 넣으면 실제 연결로 넘어간다."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.llm.base import ToolDef
from api.llm.demo_adapter import DEMO_TAG, DemoAdapter
from api.models.entities import EMBEDDING_DIM
from api.tests.conftest import Team
from api.tests.test_builder import new_session, send


def test_complete_json_and_embedding() -> None:
    a = DemoAdapter()
    text = a.complete(
        model="demo-1",
        system="",
        prompt="환불은 어떻게 하나요?",
        temperature=None,
        json_schema=None,
    ).text
    assert text.startswith(DEMO_TAG) and "환불은 어떻게" in text
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["billing", "tech"]},
            "score": {"type": "number"},
            "ok": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "name": {"type": "string"},
        },
    }
    res = a.complete(model="demo-1", system="", prompt="x", temperature=None, json_schema=schema)
    assert res.data == {
        "category": "billing",
        "score": 0,
        "ok": True,
        "tags": ["데모 tags"],
        "name": "데모 name",
    }
    chunks: list[str] = []
    a.complete(
        model="m", system="", prompt="p", temperature=None, json_schema=None, on_delta=chunks.append
    )
    assert len(chunks) == 2
    e1, e2, e3 = a.embed(
        model="m", texts=["환불 규정 안내", "환불 규정 문의", "전혀 다른 날씨 이야기"]
    )
    assert len(e1) == EMBEDDING_DIM

    def dot(x: list[float], y: list[float]) -> float:
        return sum(p * q for p, q in zip(x, y, strict=True))

    assert dot(e1, e2) > dot(e1, e3)  # 낱말이 겹치면 더 가깝다
    assert a.embed(model="m", texts=["같은 글"]) == a.embed(model="m", texts=["같은 글"])


def test_knowledge_context_is_quoted() -> None:
    out = DemoAdapter().complete(
        model="m",
        system="",
        prompt="질문\n자료:\n환불은 7일 안에 가능해요\n둘째 줄",
        temperature=None,
        json_schema=None,
    )
    assert "환불은 7일 안에 가능해요" in out.text


def test_builder_demo_sequence() -> None:
    a = DemoAdapter()
    tools = [ToolDef(n, "", {}) for n in ("get_graph", "add_node", "validate", "update_node")]
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "문의 분류 앱 만들어 줘"}]
    t1 = a.chat(model="m", system="", messages=msgs, tools=tools)
    assert [c.name for c in t1.tool_calls] == ["get_graph"]
    msgs += [
        {"role": "assistant", "content": t1.text, "tool_calls": t1.tool_calls},
        {
            "role": "tool",
            "name": "get_graph",
            "tool_call_id": "x",
            "content": '{"graph": {"nodes": [{}, {}]}}',
        },
    ]
    t2 = a.chat(model="m", system="", messages=msgs, tools=tools)
    assert t2.tool_calls[0].name == "add_node"
    assert t2.tool_calls[0].input["type"] == "llm"  # '분류' 요청이라 종류 나누기 단계
    msgs += [
        {"role": "assistant", "content": "", "tool_calls": t2.tool_calls},
        {"role": "tool", "name": "add_node", "tool_call_id": "y", "content": "{}"},
    ]
    t3 = a.chat(model="m", system="", messages=msgs, tools=tools)
    assert t3.tool_calls[0].name == "validate"
    msgs += [
        {"role": "assistant", "content": "", "tool_calls": t3.tool_calls},
        {"role": "tool", "name": "validate", "tool_call_id": "z", "content": "{}"},
    ]
    t4 = a.chat(model="m", system="", messages=msgs, tools=tools)
    assert not t4.tool_calls and DEMO_TAG in t4.text
    # 도구 없는 대화는 그냥 예시 답
    plain = a.chat(model="m", system="", messages=[{"role": "user", "content": "안녕"}], tools=[])
    assert plain.text.startswith(DEMO_TAG) and not plain.tool_calls


def _demo(client: TestClient, team: Team) -> dict[str, Any]:
    res = client.post(f"/api/v1/workspaces/{team.ws}/llm-providers/demo", headers=team.h("admin"))
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_enable_demo_is_idempotent_and_listed(client: TestClient, team: Team) -> None:
    assert _demo(client, team)["created"] is True
    assert _demo(client, team)["created"] is False
    rows = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("admin")).json()
    assert [(r["provider"], r["is_default"]) for r in rows] == [("demo", True)]
    presets = client.get("/api/v1/llm/providers", headers=team.h("admin")).json()
    assert any(
        p["key"] == "demo" for p in (presets["providers"] if isinstance(presets, dict) else presets)
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/llm-providers/demo", headers=team.h("builder")
        ).status_code
        == 403
    )


def test_builder_works_with_demo_ai_and_real_key_takes_over(client: TestClient, team: Team) -> None:
    _demo(client, team)
    app_id, sid = new_session(client, team, "데모 빌더")
    events = send(client, team, sid, "문의를 분류하는 앱을 만들어 줘")
    done = next(d for n, d in events if n == "done")
    assert DEMO_TAG in done["content"]
    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    assert any(n["data"].get("label") == "종류 나누기" for n in graph["nodes"])
    # 진짜 키를 가진 연결을 등록하면 그것이 기본이 된다(데모만 있었을 때)
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "openai",
            "label": "진짜",
            "api_key": "sk-test-1234",
            "default_model": "gpt-5.4-mini",
        },
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text
    rows = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("admin")).json()
    assert {r["provider"]: r["is_default"] for r in rows} == {"demo": False, "openai": True}
    # 진짜 연결이 있는 곳에서 데모를 켜도 기본 연결은 그대로
    client.delete(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{next(r['id'] for r in rows if r['provider'] == 'demo')}",
        headers=team.h("owner"),
    )
    assert _demo(client, team)["created"] is True
    rows = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("admin")).json()
    assert {r["provider"]: r["is_default"] for r in rows} == {"demo": False, "openai": True}


def test_demo_connection_test_passes_without_network(client: TestClient, team: Team) -> None:
    pid = _demo(client, team)["provider_id"]
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{pid}/test", headers=team.h("admin")
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True and "데모" in res.json()["message"]


def test_onboarding_does_not_count_demo_as_connected(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/onboarding"
    before = client.get(url, headers=team.h("owner"))
    assert before.status_code == 200, before.text
    _demo(client, team)
    assert client.get(url, headers=team.h("owner")).json()["ai_connected"] is False


@pytest.mark.parametrize(
    ("request_text", "labels"),
    [
        ("아무거나 만들어 줘", ["답변 쓰기"]),
        ("주간 보고 초안을 만들어서 승인 후 보내 줘", ["초안 쓰기", "담당자 승인"]),
        ("회의 메모를 할 일로 정리해 줘", ["간추리기"]),
    ],
)
def test_demo_builder_draws_connected_flow_that_validates(
    client: TestClient, team: Team, request_text: str, labels: list[str]
) -> None:
    _demo(client, team)
    app_id, sid = new_session(client, team, "데모 연결")
    send(client, team, sid, request_text)
    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    ids = {n["id"] for n in graph["nodes"]}
    by_label = {n["data"].get("label"): n for n in graph["nodes"]}
    chain = [by_label[x] for x in labels]
    for node in chain:
        assert any(e["target"] == node["id"] for e in graph["edges"])  # 들어오는 선이 있다
        assert any(e["source"] == node["id"] for e in graph["edges"])  # 나가는 선도 있다
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    # 마지막 결과가 AI가 쓴 글을 보여 준다(승인 단계는 글을 만들지 않는다)
    out = next(n for n in graph["nodes"] if n["type"] == "output")
    writer = next(n for n in chain if n["type"] == "llm")
    assert writer["id"] in out["data"]["template"]
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert v["valid"] is True, str(v["errors"])


def test_builder_turn_texts_do_not_run_together(
    client: TestClient, team: Team, fake_llm: Any
) -> None:
    from api.tests.conftest import add_llm
    from api.tests.fakes import text_turn, tool_turn

    add_llm(client, team)
    _, sid = new_session(client, team, "줄 띄우기")
    fake_llm.script = [
        tool_turn("흐름을 읽을게요.", ("get_graph", {})),
        text_turn("다 읽었어요."),
    ]
    events = send(client, team, sid, "봐 줘")
    done = next(d for n, d in events if n == "done")
    assert done["content"] == "흐름을 읽을게요.\n\n다 읽었어요."


def test_demo_ai_serves_knowledge_embeddings_but_real_key_wins(
    client: TestClient, team: Team
) -> None:
    from api.db import SessionLocal
    from api.llm.registry import resolve_llm

    _demo(client, team)
    with SessionLocal() as db:
        got = resolve_llm(db, team.ws, "default", purpose="embedding")
        assert got.provider.provider == "demo"
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "openai",
            "label": "진짜",
            "api_key": "sk-test-1234",
            "default_model": "gpt-5.4-mini",
        },
        headers=team.h("owner"),
    )
    assert res.status_code == 200
    with SessionLocal() as db:
        assert (
            resolve_llm(db, team.ws, "default", purpose="embedding").provider.provider == "openai"
        )


def test_dependency_map_hides_apps_nobody_uses(client: TestClient, team: Team) -> None:
    new_session(client, team, "혼자 있는 앱")
    out = client.get(f"/api/v1/workspaces/{team.ws}/dependencies", headers=team.h("builder")).json()
    assert all(r["kind"] != "app" for r in out["resources"])


def test_chat_missing_required_input_says_what_to_fill(client: TestClient, team: Team) -> None:
    """꼭 적어야 하는 칸을 비운 채 보내면 '잠시 후 다시'가 아니라 채울 칸을 알려 준다."""
    app_id, _ = new_session(client, team, "필수 칸")
    graph = {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {
                    "fields": [
                        {"key": "message", "type": "text", "required": True},
                        {"key": "start", "label": "시작일", "type": "text", "required": True},
                    ]
                },
            },
            {"id": "n2", "type": "output", "data": {"template": "{{n1.start}}"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    client.post(f"/api/v1/apps/{app_id}/versions", json={"note": "v1"}, headers=team.h("builder"))
    dep = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "public"},
        headers=team.h("builder"),
    ).json()
    with client.stream(
        "POST", f"/api/v1/public/apps/{dep['public_token']}/chat", json={"message": "안녕"}
    ) as res:
        from api.tests.test_builder import parse_sse

        events = parse_sse("".join(res.iter_text()))
    err = next(d for n, d in events if n == "error")
    assert "시작일" in err["message"] and "채운 뒤" in err["hint"]
