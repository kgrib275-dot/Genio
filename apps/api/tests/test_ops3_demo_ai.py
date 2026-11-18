"""데모 AI: 키 없이 훑어보고, 진짜 키를 넣으면 실제 연결로 넘어간다."""

from typing import Any

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
    assert t2.tool_calls[0].input["data"]["label"] == "데모 단계"
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
    assert any(n["data"].get("label") == "데모 단계" for n in graph["nodes"])
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
