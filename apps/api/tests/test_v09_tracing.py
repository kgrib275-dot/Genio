"""v0.9 관측 도구 확대: OpenTelemetry(OTLP)·Phoenix·Arize AX·Opik·Weave + 기존 Langfuse·LangSmith를
여러 개 동시에, 표본·실패만·내용 포함 설정, 마지막 전송 결과, 예전 설정 호환."""

import base64
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.core.crypto import encrypt_str
from api.db import SessionLocal
from api.engine import safe_http
from api.models import App, Workspace
from api.services import trace_model as tm
from api.services import tracing
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v04_triggers import echo_graph, make_app

LLM_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "type": "text"}]}},
        {"id": "n2", "type": "llm", "data": {"label": "요약", "prompt": "{{n1.message}}"}},
        {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}
FAIL_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "type": "text"}]}},
        {"id": "n2", "type": "output", "data": {"template": "{{ nope | bad }}"}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}
SECRET_ENV = "sk-env-secret-4444"  # noqa: S105
KEY = "api-key-secret-7777"
HDR = "Bearer otel-header-secret-5555"


class Sink:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = 200
        self.body: Any = {}

    def __call__(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, **kw})
        return {"status": self.status, "body": self.body, "headers": {}}

    def to(self, suffix: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["url"].endswith(suffix)]


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Sink:
    s = Sink()
    monkeypatch.setattr(safe_http, "request", s)
    return s


def _put(client: TestClient, team: Team, body: dict[str, Any], role: str = "admin") -> Any:
    return client.put(f"/api/v1/workspaces/{team.ws}/tracing", json=body, headers=team.h(role))


def _get(client: TestClient, team: Team, role: str = "admin") -> Any:
    return client.get(f"/api/v1/workspaces/{team.ws}/tracing", headers=team.h(role))


def _test(client: TestClient, team: Team, target: str, role: str = "admin") -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/tracing/test", json={"target": target}, headers=team.h(role)
    )


def _run(
    client: TestClient, team: Team, app_id: str, message: str = "안녕하세요"
) -> dict[str, Any]:
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": message}},
        headers=team.h("builder"),
    ).json()
    out: dict[str, Any] = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    return out


def _all_providers() -> list[dict[str, Any]]:
    return [
        {
            "id": "",
            "kind": "langfuse",
            "name": "LF",
            "enabled": True,
            "fields": {"host": "https://lf.example.com", "public_key": "pk-lf-1"},
            "secrets": {"secret_key": "sk-lf-secret-1111"},
        },
        {
            "kind": "langsmith",
            "name": "LS",
            "enabled": True,
            "fields": {"project": "proj"},
            "secrets": {"api_key": "lsv2-secret-2222"},
        },
        {
            "kind": "otlp",
            "name": "OTel",
            "enabled": True,
            "fields": {"endpoint": "https://otel.example.com:4318", "service_name": "my-genio"},
            "headers": [{"name": "Authorization", "value": HDR}],
        },
        {
            "kind": "phoenix",
            "name": "Phoenix",
            "enabled": True,
            "fields": {"endpoint": "https://phoenix.example.com", "project": "px"},
            "secrets": {"api_key": KEY},
        },
        {
            "kind": "arize",
            "name": "Arize",
            "enabled": True,
            "fields": {"space_id": "space-1", "project": "az"},
            "secrets": {"api_key": KEY + "a"},
        },
        {
            "kind": "opik",
            "name": "Opik",
            "enabled": True,
            "fields": {"workspace": "ws-1", "project": "op"},
            "secrets": {"api_key": KEY + "o"},
        },
        {
            "kind": "weave",
            "name": "Weave",
            "enabled": True,
            "fields": {"entity": "team", "project": "wv"},
            "secrets": {"api_key": KEY + "w"},
        },
    ]


# ---------------- 인코딩 단위 시험 ----------------
def test_otlp_ids_and_times() -> None:
    tid = tm.hex_trace_id("1b4e28ba-2fa1-11d2-883f-0016d3cca427")
    assert tid == "1b4e28ba2fa111d2883f0016d3cca427" and len(tid) == 32
    odd = tm.hex_trace_id("not-a-uuid")
    assert len(odd) == 32 and re.fullmatch(r"[0-9a-f]{32}", odd) and int(odd, 16) != 0
    sid = tm.hex_span_id("step:abc")
    assert (
        len(sid) == 16 and re.fullmatch(r"[0-9a-f]{16}", sid) and sid == tm.hex_span_id("step:abc")
    )
    assert sid != tm.hex_span_id("step:abd")
    t = datetime(2026, 11, 5, 1, 2, 3, 456789, tzinfo=UTC)
    ns = tm.unix_nano(t)
    assert isinstance(ns, str) and ns == str(int(t.timestamp()) * 10**9 + 456789000)
    # 시각 정보가 없는 값(SQLite)도 UTC로 본다
    assert tm.unix_nano(datetime(2026, 11, 5, 1, 2, 3)) == tm.unix_nano(
        datetime(2026, 11, 5, 1, 2, 3, tzinfo=UTC)
    )
    kv = [tm._kv("a", True), tm._kv("b", 7), tm._kv("c", 1.5), tm._kv("d", "x")]
    assert kv[0]["value"] == {"boolValue": True} and kv[1]["value"] == {"intValue": "7"}
    assert kv[2]["value"] == {"doubleValue": 1.5} and kv[3]["value"] == {"stringValue": "x"}


def test_uuid7_shape_and_order() -> None:
    a = tm.uuid7(datetime(2026, 1, 1, tzinfo=UTC), "x")
    b = tm.uuid7(datetime(2026, 1, 2, tzinfo=UTC), "x")
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", a)
    assert a < b and a == tm.uuid7(datetime(2026, 1, 1, tzinfo=UTC), "x")


def test_clip_redacts_and_truncates() -> None:
    assert tm.clip({"a": "짧다"}, []) == {"a": "짧다"}
    out = tm.clip({"t": "값 sk-env-secret-4444 끝"}, [SECRET_ENV])
    assert isinstance(out, str) and SECRET_ENV not in out and "****" in out
    long = tm.clip("가" * 5000, [])
    assert isinstance(long, str) and long.endswith(tm.TRUNCATED) and len(long) < 2100


def test_sampling_is_deterministic() -> None:
    ids = [f"run-{i}" for i in range(1000)]
    got = [tracing.sampled(i, 30) for i in ids]
    assert 230 <= sum(got) <= 370
    assert got == [tracing.sampled(i, 30) for i in ids]
    assert all(tracing.sampled(i, 100) for i in ids) and not any(tracing.sampled(i, 0) for i in ids)


# ---------------- 설정·권한 ----------------
def test_providers_saved_masked_and_permissions(client: TestClient, team: Team) -> None:
    body = {"providers": _all_providers(), "include_content": False}
    for role in ROLES:
        res = _put(client, team, body, role)
        assert res.status_code == (200 if role in ("owner", "admin") else 403), role
        got = _get(client, team, role)
        assert got.status_code == (200 if role in ("owner", "admin") else 403), role
        assert _test(client, team, "langfuse", role).status_code == (
            200 if role in ("owner", "admin") else 403
        ), role
    out = _put(client, team, body).json()
    kinds = [p["kind"] for p in out["providers"]]
    assert kinds == ["langfuse", "langsmith", "otlp", "phoenix", "arize", "opik", "weave"]
    assert len({p["id"] for p in out["providers"]}) == 7
    text = json.dumps(out, ensure_ascii=False)
    for secret in ("sk-lf-secret-1111", "lsv2-secret-2222", HDR, KEY, "otel-header-secret-5555"):
        assert secret not in text
    otlp = next(p for p in out["providers"] if p["kind"] == "otlp")
    assert otlp["headers"] == [{"name": "Authorization", "masked": "****5555"}]
    assert otlp["ready"] is True and otlp["fields"]["endpoint"] == "https://otel.example.com:4318"
    phoenix = next(p for p in out["providers"] if p["kind"] == "phoenix")
    assert phoenix["secrets"]["api_key"] == {"has": True, "masked": "****7777"}
    assert {p["kind"] for p in out["providers"] if p["experimental"]} == {"arize", "opik", "weave"}
    assert [k["kind"] for k in out["kinds"]] == kinds
    # 일반 워크스페이스 조회에는 암호문이 나오지 않는다
    ws = client.get(f"/api/v1/workspaces/{team.ws}", headers=team.h("member")).json()
    assert "tracing" not in ws["settings"]


def test_secret_blank_or_masked_keeps_stored_and_removed_provider_is_deleted(
    client: TestClient, team: Team
) -> None:
    out = _put(client, team, {"providers": _all_providers()}).json()
    items = out["providers"]
    phoenix = next(p for p in items if p["kind"] == "phoenix")
    otlp = next(p for p in items if p["kind"] == "otlp")
    again = _put(
        client,
        team,
        {
            "providers": [
                {
                    "id": phoenix["id"],
                    "kind": "phoenix",
                    "enabled": True,
                    "fields": {"endpoint": "https://phoenix.example.com", "project": "px2"},
                    "secrets": {"api_key": "****7777"},
                },
                {
                    "id": otlp["id"],
                    "kind": "otlp",
                    "enabled": False,
                    "fields": {"endpoint": "https://otel.example.com:4318"},
                    "headers": [
                        {"name": "Authorization", "value": ""},
                        {"name": "X-Team", "value": "t-1234"},
                    ],
                },
            ]
        },
    ).json()
    assert [p["kind"] for p in again["providers"]] == ["phoenix", "otlp"]
    ph = again["providers"][0]
    assert ph["secrets"]["api_key"]["masked"] == "****7777" and ph["fields"]["project"] == "px2"
    assert again["providers"][1]["headers"][0] == {"name": "Authorization", "masked": "****5555"}
    assert again["providers"][1]["headers"][1]["name"] == "X-Team"
    cleared = _put(
        client,
        team,
        {"providers": [{"id": phoenix["id"], "kind": "phoenix", "clear_secrets": ["api_key"]}]},
    ).json()
    assert cleared["providers"][0]["secrets"]["api_key"] == {"has": False, "masked": ""}


def test_save_validation_errors_are_two_lines(client: TestClient, team: Team) -> None:
    cases: list[dict[str, Any]] = [
        {"providers": [{"kind": "nope"}]},
        {"providers": [{"kind": "otlp", "fields": {"endpoint": "ftp://x"}}]},
        {"providers": [{"kind": "otlp", "headers": [{"name": "bad name!", "value": "x"}]}]},
        {"providers": [{"kind": "otlp", "headers": [{"name": "A", "value": "x\ny"}]}]},
        {"providers": [{"kind": "otlp"}] * 11},
    ]
    for body in cases:
        res = _put(client, team, body)
        assert res.status_code == 422, body
        detail = res.json()["detail"]
        assert detail["message"] and detail["hint"]


# ---------------- 서비스별 전송 모양 ----------------
def test_each_provider_payload(
    client: TestClient, team: Team, fake_llm: FakeAdapter, sink: Sink
) -> None:
    add_llm(client, team)
    _put(client, team, {"providers": _all_providers()})
    app_id = make_app(client, team, LLM_GRAPH, name="요약 앱")
    d = _run(client, team, app_id, "민감한-내용-123")
    assert d["status"] == "succeeded", d["error"]
    urls = [c["url"] for c in sink.calls]
    assert urls.count("https://otel.example.com:4318/v1/traces") == 1
    assert "https://phoenix.example.com/v1/traces" in urls
    assert "https://otlp.arize.com/v1/traces" in urls
    assert "https://www.comet.com/opik/api/v1/private/traces/batch" in urls
    assert "https://www.comet.com/opik/api/v1/private/spans/batch" in urls
    assert "https://trace.wandb.ai/call/upsert_batch" in urls
    assert "https://lf.example.com/api/public/ingestion" in urls
    assert "https://api.smith.langchain.com/runs/batch" in urls

    def spans_of(call: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        rs = call["body"]["resourceSpans"][0]
        return rs["resource"], rs["scopeSpans"][0]["spans"]

    def attr(items: list[dict[str, Any]], key: str) -> Any:
        return next((a["value"] for a in items if a["key"] == key), None)

    # --- OpenTelemetry
    call = next(c for c in sink.calls if c["url"].startswith("https://otel."))
    assert call["headers"]["Authorization"] == HDR
    assert call["headers"]["Content-Type"] == "application/json"
    res, spans = spans_of(call)
    assert attr(res["attributes"], "service.name") == {"stringValue": "my-genio"}
    root = spans[0]
    assert re.fullmatch(r"[0-9a-f]{32}", root["traceId"]) and "parentSpanId" not in root
    assert re.fullmatch(r"[0-9a-f]{16}", root["spanId"]) and root["name"] == "요약 앱"
    assert re.fullmatch(r"\d{19}", root["startTimeUnixNano"]) and root["status"] == {"code": 1}
    assert attr(root["attributes"], "genio.run_id") == {"stringValue": d["id"]}
    assert len(spans) == 4  # 실행 + 입력·AI·결과 단계
    assert all(
        s["parentSpanId"] == root["spanId"] and s["traceId"] == root["traceId"] for s in spans[1:]
    )
    llm = next(s for s in spans if s["name"] == "요약")
    assert attr(llm["attributes"], "gen_ai.request.model") is not None
    assert int(attr(llm["attributes"], "gen_ai.usage.input_tokens")["intValue"]) > 0
    assert attr(llm["attributes"], "gen_ai.system") is not None
    assert attr(llm["attributes"], "openinference.span.kind") is None  # 일반 OTLP에는 붙이지 않는다
    # --- Phoenix
    ph = next(c for c in sink.calls if c["url"].startswith("https://phoenix."))
    assert (
        ph["headers"]["Authorization"] == f"Bearer {KEY}"
        and ph["headers"]["x-project-name"] == "px"
    )
    res, spans = spans_of(ph)
    assert attr(res["attributes"], "openinference.project.name") == {"stringValue": "px"}
    assert attr(spans[0]["attributes"], "openinference.span.kind") == {"stringValue": "CHAIN"}
    llm = next(s for s in spans if s["name"] == "요약")
    assert attr(llm["attributes"], "openinference.span.kind") == {"stringValue": "LLM"}
    assert int(attr(llm["attributes"], "llm.token_count.total")["intValue"]) > 0
    # --- Arize AX: 두 가지 헤더 이름을 함께 보낸다
    az = next(c for c in sink.calls if c["url"].startswith("https://otlp.arize.com"))
    for name in ("arize-space-id", "space_id"):
        assert az["headers"][name] == "space-1"
    for name in ("arize-api-key", "api_key"):
        assert az["headers"][name] == KEY + "a"
    res, _ = spans_of(az)
    assert attr(res["attributes"], "model_id") == {"stringValue": "az"}
    # --- Opik
    traces = next(c for c in sink.calls if c["url"].endswith("/traces/batch"))
    spans_call = next(c for c in sink.calls if c["url"].endswith("/spans/batch"))
    assert traces["headers"]["Authorization"] == KEY + "o"
    assert traces["headers"]["Comet-Workspace"] == "ws-1"
    trace = traces["body"]["traces"][0]
    assert trace["project_name"] == "op" and trace["name"] == "요약 앱"
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", trace["id"]
    )
    ospans = spans_call["body"]["spans"]
    assert len(ospans) == 3 and all(s["trace_id"] == trace["id"] for s in ospans)
    ollm = next(s for s in ospans if s["type"] == "llm")
    assert ollm["usage"]["total_tokens"] > 0 and ollm["model"]
    # --- Weave
    wv = next(c for c in sink.calls if c["url"].endswith("/call/upsert_batch"))
    assert (
        wv["headers"]["Authorization"]
        == "Basic " + base64.b64encode(f"api:{KEY}w".encode()).decode()
    )
    batch = wv["body"]["batch"]
    assert [b["mode"] for b in batch] == ["start", "end"] * 4
    start = batch[0]["req"]["start"]
    assert start["project_id"] == "team/wv" and start["parent_id"] is None
    assert batch[2]["req"]["start"]["parent_id"] == start["id"]
    assert batch[1]["req"]["end"]["id"] == start["id"]
    # --- 기본값(내용 빼고): 어떤 서비스에도 입력 글이 가지 않는다
    for c in sink.calls:
        assert "민감한-내용-123" not in json.dumps(c["body"], ensure_ascii=False), c["url"]
    # 비밀값은 설정 조회에도 없다
    assert KEY not in _get(client, team).text


def test_privacy_content_toggle_truncation_and_env_redaction(
    client: TestClient, team: Team, sink: Sink
) -> None:
    graph = echo_graph()
    for n in graph["nodes"]:
        if n["type"] == "output":
            n["data"]["template"] = "{{env.TOKEN}} / {{n1.message}}"
    app_id = make_app(client, team, graph, name="내용 앱")
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        app.env_vars = [
            {"key": "TOKEN", "secret": True, "value_enc": encrypt_str(SECRET_ENV).decode()}
        ]
        db.commit()
    _put(
        client,
        team,
        {
            "include_content": True,
            "providers": [
                {
                    "kind": "langfuse",
                    "enabled": True,
                    "fields": {"host": "https://lf.example.com", "public_key": "pk"},
                    "secrets": {"secret_key": "sk-lf-xxxx1111"},
                },
                {"kind": "otlp", "enabled": True, "fields": {"endpoint": "https://o.example.com"}},
            ],
        },
    )
    assert _get(client, team).json()["include_content"] is True
    long_msg = "민감한-내용-123 " + "가" * 3000
    d = _run(client, team, app_id, long_msg)
    assert d["status"] == "succeeded", d["error"]
    body = json.dumps([c["body"] for c in sink.calls], ensure_ascii=False)
    assert "민감한-내용-123" in body  # 내용 포함을 켰으니 들어간다
    assert SECRET_ENV not in body  # 비밀 환경 값은 가려진다
    assert "****" in body and tm.TRUNCATED in body
    assert "가" * 2100 not in body  # 2KB로 잘렸다
    lf = next(c for c in sink.calls if c["url"].endswith("/ingestion"))
    assert "input" in lf["body"]["batch"][0]["body"]
    # 다시 끄면 내용이 빠진다
    sink.calls.clear()
    _put(client, team, {"include_content": False})
    _run(client, team, app_id, "또-민감한-내용-456")
    assert sink.calls and "민감한-내용-456" not in json.dumps(
        [c["body"] for c in sink.calls], ensure_ascii=False
    )
    lf = next(c for c in sink.calls if c["url"].endswith("/ingestion"))
    assert "input" not in lf["body"]["batch"][0]["body"]


def test_failed_step_error_text_is_generic_without_content(
    client: TestClient, team: Team, sink: Sink
) -> None:
    app_id = make_app(client, team, FAIL_GRAPH, name="실패 앱")
    otlp = {"kind": "otlp", "enabled": True, "fields": {"endpoint": "https://o.example.com"}}
    _put(client, team, {"providers": [otlp]})
    d = _run(client, team, app_id, "x")
    assert d["status"] == "failed"
    root = sink.calls[0]["body"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert root["status"]["code"] == 2 and root["status"]["message"] == "실행이 실패했어요."
    assert "nope" not in json.dumps(sink.calls[0]["body"], ensure_ascii=False)


# ---------------- 표본·실패만 ----------------
def test_sampling_and_only_failed(client: TestClient, team: Team, sink: Sink) -> None:
    def otlp(host: str, **kw: Any) -> dict[str, Any]:
        return {"kind": "otlp", "enabled": True, "fields": {"endpoint": f"https://{host}"}, **kw}

    _put(
        client,
        team,
        {
            "providers": [
                otlp("never.example.com", sample_rate=0),
                otlp("failed.example.com", only_failed=True),
                otlp("always.example.com", sample_rate=100),
                {**otlp("off.example.com"), "enabled": False},
            ]
        },
    )
    ok_app = make_app(client, team, echo_graph(), name="성공 앱")
    bad_app = make_app(client, team, FAIL_GRAPH, name="실패 앱")
    assert _run(client, team, ok_app, "a")["status"] == "succeeded"
    hosts = [c["url"].split("/")[2] for c in sink.calls]
    assert hosts == ["always.example.com"]
    sink.calls.clear()
    assert _run(client, team, bad_app, "a")["status"] == "failed"
    hosts = sorted(c["url"].split("/")[2] for c in sink.calls)
    assert hosts == ["always.example.com", "failed.example.com"]
    # 설정 저장 값이 0~100 밖이면 범위로 맞춘다
    out = _put(client, team, {"providers": [otlp("x.example.com", sample_rate=500)]}).json()
    assert out["providers"][0]["sample_rate"] == 100


# ---------------- 마지막 전송 결과·실패해도 실행은 그대로 ----------------
def test_last_status_and_failure_does_not_break_run(
    client: TestClient, team: Team, sink: Sink, caplog: pytest.LogCaptureFixture
) -> None:
    _put(
        client,
        team,
        {"providers": [{"kind": "langsmith", "enabled": True, "secrets": {"api_key": KEY}}]},
    )
    app_id = make_app(client, team, echo_graph(), name="앱")
    caplog.set_level(logging.DEBUG)
    assert _get(client, team).json()["providers"][0]["last"] is None
    sink.status = 500
    assert _run(client, team, app_id, "x")["status"] == "succeeded"
    last = _get(client, team).json()["providers"][0]["last"]
    assert last["ok"] is False and "응답 500" in last["message"] and last["at"]
    sink.status = 401
    _run(client, team, app_id, "x")
    assert "인증 실패" in _get(client, team).json()["providers"][0]["last"]["message"]
    sink.status = 200
    _run(client, team, app_id, "x")
    last = _get(client, team).json()["providers"][0]["last"]
    assert last["ok"] is True
    assert KEY not in caplog.text and KEY not in _get(client, team).text


def test_exception_in_sender_is_swallowed(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError(f"연결 거부 {KEY}")

    monkeypatch.setattr(safe_http, "request", boom)
    _put(
        client,
        team,
        {
            "providers": [
                {
                    "kind": "otlp",
                    "enabled": True,
                    "fields": {"endpoint": "https://o.example.com"},
                    "headers": [{"name": "A", "value": KEY}],
                }
            ]
        },
    )
    app_id = make_app(client, team, echo_graph(), name="앱")
    assert _run(client, team, app_id, "x")["status"] == "succeeded"
    last = _get(client, team).json()["providers"][0]["last"]
    assert last["ok"] is False and KEY not in json.dumps(last, ensure_ascii=False)


# ---------------- 예전 설정 호환 ----------------
def test_legacy_settings_still_work_and_migrate(client: TestClient, team: Team, sink: Sink) -> None:
    with SessionLocal() as db:
        ws = db.get(Workspace, team.ws)
        assert ws is not None
        ws.settings = {
            **(ws.settings or {}),
            "tracing": {
                "langfuse": {
                    "enabled": True,
                    "host": "https://lf.example.com",
                    "public_key": "pk-lf-1",
                    "secret_key_enc": encrypt_str("sk-lf-legacy-9999").decode(),
                },
                "langsmith": {
                    "enabled": True,
                    "project": "old",
                    "api_key_enc": encrypt_str("lsv2-legacy-8888").decode(),
                },
            },
        }
        db.commit()
    cfg = _get(client, team).json()
    assert [p["id"] for p in cfg["providers"]] == ["langfuse", "langsmith"]
    assert cfg["langfuse"]["secret_key"] == "****9999"  # noqa: S105
    assert cfg["langsmith"]["project"] == "old"
    assert "sk-lf-legacy-9999" not in json.dumps(cfg)
    app_id = make_app(client, team, echo_graph(), name="앱")
    assert _run(client, team, app_id, "x")["status"] == "succeeded"
    assert {c["url"] for c in sink.calls} == {
        "https://lf.example.com/api/public/ingestion",
        "https://api.smith.langchain.com/runs/batch",
    }
    # 저장하면 목록으로 옮겨지고 예전 키는 사라지며 키는 그대로 쓸 수 있다
    sink.calls.clear()
    assert _put(client, team, {"include_content": False}).status_code == 200
    with SessionLocal() as db:
        ws = db.get(Workspace, team.ws)
        assert ws is not None
        stored = (ws.settings or {})["tracing"]
        assert "langfuse" not in stored and "langsmith" not in stored
        assert [p["id"] for p in stored["providers"]] == ["langfuse", "langsmith"]
    _run(client, team, app_id, "x")
    assert len(sink.calls) == 2
    # 옛 모양 입력도 계속 받는다
    out = _put(client, team, {"langsmith": {"enabled": False, "project": "new"}}).json()
    assert out["langsmith"]["project"] == "new" and out["langsmith"]["enabled"] is False
    assert out["langsmith"]["has_key"] is True and out["langfuse"]["enabled"] is True


# ---------------- 연결 시험 ----------------
def test_connection_test_for_each_provider(client: TestClient, team: Team, sink: Sink) -> None:
    out = _put(client, team, {"providers": _all_providers()}).json()
    for p in out["providers"]:
        sink.calls.clear()
        res = _test(client, team, p["id"]).json()
        assert res["ok"] is True, (p["kind"], res)
        assert sink.calls, p["kind"]
        body = json.dumps([c["body"] for c in sink.calls], ensure_ascii=False)
        assert "Genio 연결 시험" in body
    last = _get(client, team).json()["providers"][0]["last"]
    assert last["ok"] is True and "연결 시험" in last["message"]
    # 실패 문장은 두 줄 규칙의 첫 줄(원인)을 알려 준다
    sink.status = 401
    bad = _test(client, team, out["providers"][2]["id"]).json()
    assert bad["ok"] is False and "인증" in bad["message"]
    sink.status = 200
    sink.body = {"partialSuccess": {"rejectedSpans": 2}}
    part = _test(client, team, out["providers"][2]["id"]).json()
    assert part["ok"] is False and "일부" in part["message"]
    sink.body = {}
    # 필수 칸이 비어 있거나 모르는 서비스
    only = _put(
        client,
        team,
        {"providers": [{"kind": "opik", "enabled": True, "fields": {"workspace": "w"}}]},
    ).json()
    not_ready = _test(client, team, only["providers"][0]["id"]).json()
    assert not_ready["ok"] is False and "필수" in not_ready["message"]
    assert _test(client, team, "zzz").json()["ok"] is False
    assert _test(client, team, "langfuse").json()["ok"] is False  # 예전 이름·저장 안 됨
