"""v0.8 Dify 앱 가져오기: DSL 변환, 변수 참조 바꾸기, 자리 표시 단계, 변환 보고서, 권한, 실제 실행.

시험 자료(fixtures/dify/*.yml)는 Dify DSL 형식을 알고 있는 대로 직접 쓴 것이다.
실제 Dify에서 내보낸 파일로는 확인하지 못했다.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.services.dify_import import convert
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v02_features import chat, deploy
from api.tests.test_v05_engine import start

FX = Path(__file__).parent / "fixtures" / "dify"


def _fx(name: str) -> bytes:
    return (FX / name).read_bytes()


def _import(
    client: TestClient, team: Team, data: bytes, role: str = "builder", **extra: Any
) -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/apps/import-dify",
        files={"file": ("app.yml", data, "text/yaml")},
        data=extra,
        headers=team.h(role),
    )


def _by_id(graph: dict[str, Any]) -> dict[str, Any]:
    return {n["id"]: n for n in graph["nodes"]}


# ---------------- 변환(DB 없이) ----------------
def test_chatflow_conversion() -> None:
    c = convert(_fx("chatflow_simple.yml"))
    assert c.app_type == "chat" and c.name == "사내 도우미" and c.icon == "🤖"
    nodes = _by_id(c.graph)
    assert [n["type"] for n in c.graph["nodes"]] == ["input", "llm", "output"]
    # 챗은 첫 입력 칸이 message, 시작 단계 id는 n1
    assert nodes["n1"]["data"]["fields"][0]["key"] == "message"
    llm = nodes["n2"]["data"]
    assert llm["prompt"] == "{{n1.message}}"  # 사용자 글이 없어 기억 질문 틀을 썼다
    assert "{{env.COMPANY}}" in llm["system"] and llm["memory"] is True
    assert llm["temperature"] == 0.7 and "gpt-4o" in llm["note"]
    assert nodes["n3"]["data"]["template"] == "{{n2.text}}"
    assert [(e["source"], e["target"]) for e in c.graph["edges"]] == [("n1", "n2"), ("n2", "n3")]
    f = c.features
    assert f["opening_statement"].startswith("안녕하세요") and f["follow_up"] == {"enabled": True}
    assert f["moderation"]["keywords"] == ["욕설", "비속어"] and f["speech"]["stt"] is True
    assert f["suggested_questions"] == ["연차는 며칠인가요?", "재택근무 규정은?"]
    # 환경 값: 비밀은 값을 가져오지 않는다
    assert {"key": "COMPANY", "secret": False, "value": "효성"} in c.env_vars
    assert {"key": "SECRET_TOKEN", "secret": True, "value": ""} in c.env_vars
    assert "super-secret-value" not in str(c.report.dump())
    assert any("visit_count" in w for w in c.report.warnings)


def test_workflow_branch_conversion() -> None:
    c = convert(_fx("workflow_branch.yml"))
    assert c.app_type == "workflow"
    nodes = _by_id(c.graph)
    assert nodes["n1"]["type"] == "input"
    fields = {f["key"]: f for f in nodes["n1"]["data"]["fields"]}
    assert fields["amount"]["type"] == "number" and "선택: 한국, 일본" in fields["country"]["label"]
    cond = nodes["n2"]["data"]
    assert (
        cond["cases"] == [{"id": "true", "when": "{{n1.amount}} > 100"}] and cond["else"] == "else"
    )
    handles = {(e["source"], e["target"]): e.get("sourceHandle") for e in c.graph["edges"]}
    assert handles[("n2", "n3")] == "true" and handles[("n2", "n6")] == "else"
    code = nodes["n3"]["data"]
    assert code["language"] == "python" and code["inputs"] == {"amount": "{{n1.amount}}"}
    assert code["code"].rstrip().endswith("result = main(amount=inputs.get('amount'))")
    http = nodes["n4"]["data"]
    assert http["method"] == "POST" and http["url"].endswith("/discounts?source=genio")
    assert http["headers"] == {"Content-Type": "application/json"} and "auth" not in http
    assert "sk-live-do-not-copy" not in str(c.report.dump()) + str(c.graph)
    # 값 이름 바꾸기: http의 status_code → status, 템플릿의 변수 이름 → 경로
    assert nodes["n5"]["data"]["template"] == (
        "{{ n1.customer }}님, 할인 {{ n3.discount }}원이 적용돼요. (응답 {{ n4.status }})"
    )
    assert nodes["n7"]["data"]["template"] == "{{n5.output}}"
    notes = [a["message"] for a in c.report.needs_attention]
    assert any("Bearer" in m for m in notes) and any("감싸졌어요" in m for m in notes)


def test_knowledge_chatbot_context_and_kb_placeholder() -> None:
    c = convert(_fx("chatbot_kb.yml"))
    nodes = _by_id(c.graph)
    kb = nodes["n2"]["data"]
    assert nodes["n2"]["type"] == "knowledge_search" and kb["kb_id"] == "" and kb["top_k"] == 4
    assert kb["query"] == "{{n1.message}}" and kb["score_threshold"] == 0.4
    llm = nodes["n3"]["data"]
    assert "{{n2.context}}" in llm["system"] and "{{#context#}}" not in llm["system"]
    assert llm["prompt"] == "{{n1.message}}"
    assert any("지식베이스 2개" in a["message"] for a in c.report.needs_attention)


def test_model_config_chat_and_agent_and_completion() -> None:
    chat_app = convert(_fx("chat_modelconfig.yml"))
    n = _by_id(chat_app.graph)
    assert chat_app.app_type == "chat" and [x["type"] for x in chat_app.graph["nodes"]] == [
        "input",
        "knowledge_search",
        "llm",
        "output",
    ]
    assert [f["key"] for f in n["n1"]["data"]["fields"]] == ["message", "name", "company"]
    assert "{{n1.company}}" in n["n3"]["data"]["system"]  # {{company}} → 입력 칸 값
    assert any("{{변수}}" in w for w in chat_app.report.warnings)  # 시작 인사 안의 변수

    agent = convert(_fx("agent_chat.yml"))
    n = _by_id(agent.graph)
    assert agent.app_type == "chat" and n["n3"]["type"] == "agent"
    assert (
        n["n3"]["data"]["max_iterations"] == 6
        and "{{n2.context}}" in n["n3"]["data"]["instruction"]
    )
    assert any("google_search" in a["message"] for a in agent.report.needs_attention)

    completion = convert(
        """
app: {mode: completion, name: 문장 완성}
kind: app
model_config:
  model: {provider: openai, name: gpt-4o-mini, completion_params: {temperature: 0.5}}
  pre_prompt: '{{topic}}에 대해 한 문단으로 써 주세요.'
  user_input_form:
  - paragraph: {label: 주제, variable: topic, required: true}
"""
    )
    assert completion.app_type == "workflow"
    n = _by_id(completion.graph)
    assert n["n1"]["data"]["fields"][0]["key"] == "topic"
    assert n["n2"]["data"]["prompt"] == "{{n1.topic}}에 대해 한 문단으로 써 주세요."
    assert any("문장 완성형" in w for w in completion.report.warnings)


def test_unsupported_nodes_become_disabled_placeholders() -> None:
    c = convert(_fx("workflow_unsupported.yml"))
    nodes = _by_id(c.graph)
    # 도구 단계와 하위 단계가 여러 개인 반복은 꺼 둔 자리 표시 단계
    assert nodes["n2"]["disabled"] is True and nodes["n2"]["type"] == "template"
    assert nodes["n4"]["disabled"] is True
    assert [u["dify_type"] for u in c.report.unsupported] == ["tool", "iteration"]
    # 하위 단계가 하나인 반복은 '항목마다 반복'으로 바뀐다({{iter.item}} → {{item}})
    it = nodes["n3"]
    assert it["type"] == "iteration" and "disabled" not in it
    assert it["data"]["items"] == "{{n1.topics}}" and it["data"]["output_key"] == "text"
    assert it["data"]["operation"]["type"] == "llm"
    assert "{{item}}" in it["data"]["operation"]["data"]["prompt"]
    # 연결은 그대로 남아 흐름 모양이 보인다. 반복 안의 연결은 가져오지 않는다.
    assert [(e["source"], e["target"]) for e in c.graph["edges"]] == [
        ("n1", "n2"),
        ("n2", "n3"),
        ("n3", "n4"),
        ("n4", "n5"),
    ]
    assert nodes["n5"]["data"]["template"] == "summaries: {{n3.results}}\nsearch: {{n2.output}}"
    # 캔버스 메모(Lexical JSON)는 글자만 꺼낸다
    assert c.graph["notes"][0]["text"] == "검색 결과를 요약하는 실험용 흐름"


def test_selector_rewriting_and_sys_values() -> None:
    c = convert(
        """
app: {mode: advanced-chat, name: sel}
kind: app
workflow:
  graph:
    edges:
    - {id: e1, source: s, target: l, sourceHandle: source}
    - {id: e2, source: l, target: a, sourceHandle: source}
    nodes:
    - id: s
      data: {type: start, title: S, variables: [{variable: photo, label: P, type: file, required: false}]}
      position: {x: 0, y: 0}
    - id: l
      data:
        type: llm
        title: L
        model: {provider: openai, name: gpt-4o, completion_params: {}}
        prompt_template:
        - {role: user, text: '{{#sys.query#}} / {{#sys.files#}} / {{#sys.user_id#}} / {{#s.photo#}} / {{#nowhere.x#}}'}
        vision: {enabled: true, configs: {variable_selector: [sys, files]}}
      position: {x: 300, y: 0}
    - id: a
      data: {type: answer, title: A, answer: '{{#l.text#}}'}
      position: {x: 600, y: 0}
"""
    )
    llm = _by_id(c.graph)["n2"]["data"]
    # sys.query → 입력 칸, sys.files·시작 파일 값 → 파일 칸, 모르는 값은 빈 값 + 알림
    assert llm["prompt"] == "{{n1.message}} / {{n1.photo}} /  / {{n1.photo}} / "
    assert llm["images"] == ["{{n1.photo}}"]
    joined = " ".join(c.report.warnings)
    assert "sys.user_id" in joined and "nowhere" in joined


def test_human_input_and_logic_nodes() -> None:
    c = convert(
        """
app: {mode: workflow, name: logic}
kind: app
workflow:
  graph:
    edges:
    - {id: e1, source: s, target: h}
    - {id: e2, source: h, target: ok, sourceHandle: approve}
    - {id: e3, source: h, target: no, sourceHandle: reject}
    nodes:
    - id: s
      data: {type: start, title: S, variables: [{variable: txt, label: T, type: text-input}]}
      position: {x: 0, y: 0}
    - id: h
      data:
        type: human-input
        title: 확인
        form_content: '{{#s.txt#}} 진행할까요?'
        inputs: []
        user_actions: [{id: approve, title: 승인}, {id: reject, title: 반려}]
      position: {x: 300, y: 0}
    - id: ok
      data: {type: end, title: OK, outputs: [{variable: r, value_selector: [h, __action_id]}]}
      position: {x: 600, y: -100}
    - id: no
      data: {type: end, title: NO, outputs: []}
      position: {x: 600, y: 100}
"""
    )
    nodes = _by_id(c.graph)
    assert nodes["n2"]["type"] == "approval" and nodes["n2"]["data"]["branch"] is True
    handles = {(e["source"], e["target"]): e.get("sourceHandle") for e in c.graph["edges"]}
    assert handles[("n2", "n3")] == "approved" and handles[("n2", "n4")] == "rejected"


def test_alias_and_bad_input_errors() -> None:
    from api.core.errors import AppError

    for raw, code in (
        (b"a: [1, 2\nb: {", 422),  # 깨진 YAML
        (b"- just\n- a list\n", 422),  # 객체가 아님
        (b"hello: world\n", 422),  # Dify 파일이 아님
        (b"a: &x [1,2,3]\nb: *x\n", 422),  # 별칭(부풀리기 공격)
        (
            b"app: {mode: rag-pipeline, name: x}\nkind: app\nworkflow: {graph: {nodes: [{id: a}]}}\n",
            422,
        ),
        (b"x: " + b"a" * (2 * 1024 * 1024 + 1), 413),
    ):
        with pytest.raises(AppError) as exc:
            convert(raw)
        assert exc.value.status == code
        assert exc.value.message and exc.value.hint


# ---------------- API ----------------
def test_import_api_creates_draft_and_report(client: TestClient, team: Team) -> None:
    r = _import(client, team, _fx("workflow_unsupported.yml"))
    assert r.status_code == 201, r.text
    body = r.json()
    app = body["app"]
    assert app["name"] == "혼합 흐름" and app["type"] == "workflow" and app["status"] == "draft"
    rep = body["report"]
    assert rep["stats"]["unsupported"] == 2 and rep["mode"] == "workflow"
    assert rep["validation_errors"] == []
    got = client.get(f"/api/v1/apps/{app['id']}", headers=team.h("builder")).json()
    assert got["draft_graph"]["nodes"][1]["disabled"] is True
    # 활동 기록에 남는다
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).json()
    items = logs["items"] if isinstance(logs, dict) else logs
    assert any(x["action"] == "app.import_dify" for x in items)


def test_import_api_json_body_project_and_errors(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/apps/import-dify"
    h = team.h("builder")
    text = _fx("chatbot_kb.yml").decode("utf-8")
    ok = client.post(url, json={"text": text}, headers=h)
    assert ok.status_code == 201 and ok.json()["report"]["stats"]["needs_attention"] >= 1
    # 만들어 둔 프로젝트가 아니면 404
    bad_project = client.post(url, json={"text": text, "project_id": "no-such"}, headers=h)
    assert bad_project.status_code == 404
    # 두 줄 오류
    for res in (
        client.post(url, json={"text": "a: [1,"}, headers=h),
        client.post(url, json={"nope": 1}, headers=h),
        client.post(url, files={"other": ("x.yml", b"a: 1")}, headers=h),
        _import(client, team, b"hello: world"),
    ):
        assert res.status_code in (400, 422), res.text
        d = res.json()["detail"]
        assert d["message"] and d["hint"]
    big = _import(client, team, b"x: " + b"a" * (2 * 1024 * 1024 + 10))
    assert big.status_code == 413 and big.json()["detail"]["hint"]


@pytest.mark.parametrize("role", ROLES)
def test_import_permissions(client: TestClient, team: Team, role: str) -> None:
    r = _import(client, team, _fx("chatflow_simple.yml"), role=role)
    allowed = role in ("owner", "admin", "builder")
    assert (r.status_code == 201) == allowed, (role, r.status_code, r.text)
    if not allowed:
        assert r.status_code == 403


def test_import_requires_login_and_membership(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    url = f"/api/v1/workspaces/{team.ws}/apps/import-dify"
    files = {"file": ("a.yml", _fx("chatflow_simple.yml"), "text/yaml")}
    assert client.post(url, files=files).status_code == 401
    assert client.post(url, files=files, headers=outsider).status_code in (403, 404)


# ---------------- 가져온 흐름이 실제로 도는지 ----------------
def test_imported_workflow_runs_both_branches(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_http(method: str, url: str, **kw: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kw})
        return {"status": 201, "headers": {}, "body": {"ok": True}}

    monkeypatch.setattr(safe_http, "request", fake_http)
    r = _import(client, team, _fx("workflow_branch.yml"))
    assert r.status_code == 201 and r.json()["report"]["validation_errors"] == [], r.json()[
        "report"
    ]
    app_id = r.json()["app"]["id"]
    big = start(client, team, app_id, {"customer": "김길동", "amount": 200, "country": "한국"})
    assert big["status"] == "succeeded", big["error"]
    assert big["output"]["text"] == "김길동님, 할인 20.0원이 적용돼요. (응답 201)"
    assert calls and calls[0]["method"] == "POST" and "source=genio" in calls[0]["url"]
    small = start(client, team, app_id, {"customer": "이영희", "amount": 50, "country": "일본"})
    assert small["status"] == "succeeded", small["error"]
    assert small["output"]["text"] == "이영희님, 이번 주문은 할인 대상이 아니에요."
    assert len(calls) == 1  # 작은 주문은 외부 호출을 건너뛴다


def test_imported_javascript_and_operators_run(client: TestClient, team: Team) -> None:
    text = """
app: {mode: workflow, name: js}
kind: app
workflow:
  graph:
    edges:
    - {id: e1, source: s, target: c}
    - {id: e2, source: c, target: j}
    - {id: e3, source: j, target: i, sourceHandle: c1}
    - {id: e4, source: i, target: e}
    - {id: e5, source: j, target: e, sourceHandle: 'false'}
    nodes:
    - id: s
      data:
        type: start
        title: S
        variables:
        - {variable: a, label: A, type: number, required: true}
        - {variable: b, label: B, type: number, required: true}
        - {variable: word, label: W, type: text-input, required: true}
      position: {x: 0, y: 0}
    - id: c
      data:
        type: code
        title: 합계
        code_language: javascript
        code: 'function main({a, b}) { return {sum: a + b}; }'
        variables:
        - {variable: a, value_selector: [s, a]}
        - {variable: b, value_selector: [s, b]}
      position: {x: 300, y: 0}
    - id: j
      data:
        type: if-else
        title: 조건
        cases:
        - case_id: c1
          logical_operator: or
          conditions:
          - {comparison_operator: contains, variable_selector: [s, word], value: 안녕}
          - {comparison_operator: '>', variable_selector: [c, sum], value: '10', varType: number}
      position: {x: 600, y: 0}
    - id: i
      data: {type: template-transform, title: T, template: 'x', variables: []}
      position: {x: 900, y: 0}
    - id: e
      data: {type: end, title: E, outputs: [{variable: sum, value_selector: [c, sum]}]}
      position: {x: 1200, y: 0}
"""
    r = _import(client, team, text.encode("utf-8"))
    assert r.status_code == 201, r.text
    assert r.json()["report"]["validation_errors"] == [], r.json()["report"]
    app_id = r.json()["app"]["id"]
    nodes = {n["id"]: n for n in r.json()["app"]["draft_graph"]["nodes"]}
    assert nodes["n3"]["data"]["cases"][0]["when"] == (
        "(contains({{n1.word}}, '안녕')) or ({{n2.sum}} > 10)"
    )
    # 자바스크립트 코드(함수 main({a, b}))가 실제로 돈다. 조건이 거짓이면 아래 단계를 건너뛰고 모인다.
    low = start(client, team, app_id, {"a": 3, "b": 4, "word": "hello"})
    assert low["status"] == "succeeded", low["error"]
    assert low["output"]["text"] == "7"
    assert "n4" not in {s["node_id"] for s in low["steps"]}
    # '또는' 조건: 글에 '안녕'이 들어 있거나 합이 10보다 크면 참
    high = start(client, team, app_id, {"a": 8, "b": 9, "word": "hello"})
    assert high["status"] == "succeeded" and high["output"]["text"] == "17"
    assert "n4" in {s["node_id"] for s in high["steps"]}
    greet = start(client, team, app_id, {"a": 1, "b": 1, "word": "안녕하세요"})
    assert "n4" in {s["node_id"] for s in greet["steps"]} and greet["output"]["text"] == "2"


def test_imported_chatflow_answers_with_fake_llm(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    r = _import(client, team, _fx("chatflow_simple.yml"))
    assert r.status_code == 201 and r.json()["report"]["validation_errors"] == []
    app_id = r.json()["app"]["id"]
    h = team.h("builder")
    assert client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h).status_code == 201
    token = deploy(client, team, app_id)
    events = chat(client, token, "연차는 며칠인가요?")
    answer = next(d for n, d in events if n == "answer")["text"]
    assert answer.startswith("요약:") and "연차는 며칠인가요?" in answer
    # 시스템 지시의 환경 값이 채워진다
    assert any("효성" in c["system"] for c in fake_llm.calls)
    # 가져온 앱 기능(시작 인사·추천 질문)이 공유 화면 정보에 있다
    info = client.get(f"/api/v1/public/apps/{token}").json()
    assert info["features"]["opening_statement"].startswith("안녕하세요")
    assert info["features"]["suggested_questions"][0] == "연차는 며칠인가요?"


@pytest.mark.parametrize("name", sorted(p.name for p in FX.glob("*.yml")))
def test_every_fixture_imports_without_validation_errors(
    client: TestClient, team: Team, name: str
) -> None:
    r = _import(client, team, _fx(name))
    assert r.status_code == 201, r.text
    rep = r.json()["report"]
    assert rep["validation_errors"] == [], (name, rep["validation_errors"])
    # 보고서는 읽을 수 있는 목록(단계마다 이름·종류)으로만 이뤄진다
    for item in rep["converted"]:
        assert item["label"] and item["dify_type"] and item["genio_type"]
