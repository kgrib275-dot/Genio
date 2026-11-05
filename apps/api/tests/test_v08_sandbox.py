"""v0.8 코드 실행 격리 서버(sandbox), 엔진 쪽 클라이언트·되돌림, 상태 화면 항목, Sentry 정리."""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.core import sentry as sentry_mod
from api.db import SessionLocal
from api.engine import code_runner, js_runner, sandbox_client
from api.engine.executor import RunServices
from api.services import status as status_svc
from nodes import NodeError
from sandbox import main as sandbox_main
from sandbox import runner as sandbox_runner

KEY = "test-sandbox-key-0123456789"
_REAL_CLIENT = httpx.Client  # 시험에서 httpx.Client를 바꾸기 전의 진짜 클래스


@pytest.fixture
def sandbox_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("GENIO_SANDBOX_KEY", KEY)
    with TestClient(sandbox_main.app) as c:
        yield c


def _post(c: TestClient, body: dict[str, Any], key: str | None = KEY) -> Any:
    headers = {"X-Sandbox-Key": key} if key is not None else {}
    return c.post("/run", json=body, headers=headers)


# ---------------- 실행기(자식 프로세스) ----------------
def test_runner_python_and_javascript() -> None:
    py = sandbox_runner.run_code("python", "result = {'x': inputs['n'] * 2}", {"n": 21}, 10)
    assert py == {"ok": True, "result": {"x": 42}}
    non_dict = sandbox_runner.run_code("python", "result = 5", {}, 10)
    assert non_dict == {"ok": True, "result": {"value": 5}}
    js = sandbox_runner.run_code("javascript", "result = {y: inputs.n + 1}", {"n": 1}, 10)
    assert js == {"ok": True, "result": {"y": 2}}
    ret = sandbox_runner.run_code("javascript", "return inputs.n * 3", {"n": 2}, 10)
    assert ret == {"ok": True, "result": {"value": 6}}


def test_runner_errors_are_mapped() -> None:
    err = sandbox_runner.run_code("python", "result = 1/0", {}, 10)
    assert err["ok"] is False and err["kind"] == "error" and "ZeroDivisionError" in err["error"]
    bad_import = sandbox_runner.run_code("python", "import os\nresult = {}", {}, 10)
    assert bad_import["ok"] is False and "os" in bad_import["error"]
    syntax = sandbox_runner.run_code("python", "def (:", {}, 10)
    assert syntax["ok"] is False and "문법" in syntax["error"]
    js_err = sandbox_runner.run_code("javascript", "throw new Error('boom')", {}, 10)
    assert js_err["ok"] is False and "boom" in js_err["error"]
    assert sandbox_runner.run_code("ruby", "x", {}, 5)["ok"] is False


def test_runner_timeouts_kill_runaway_code() -> None:
    t = time.perf_counter()
    py = sandbox_runner.run_code("python", "while True:\n    pass", {}, 1)
    assert py["ok"] is False and py["kind"] == "timeout"
    js = sandbox_runner.run_code("javascript", "while (true) {}", {}, 1)
    assert js["ok"] is False and js["kind"] == "timeout"
    assert time.perf_counter() - t < 15  # 서버가 매달리지 않는다


def test_runner_output_cap_and_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    big = sandbox_runner.run_code("javascript", "result = {s: 'x'.repeat(900000)}", {}, 10)
    assert big["ok"] is True  # 1MB 안쪽이라 통과
    monkeypatch.setattr(sandbox_runner, "MAX_OUTPUT_BYTES", 1000)
    too_big = sandbox_runner.run_code("python", "result = {'s': 'x' * 5000}", {}, 10)
    assert too_big["ok"] is False and too_big["kind"] == "output"
    assert sandbox_runner.clamp_timeout(0) == 1.0
    assert sandbox_runner.clamp_timeout(999) == 60.0
    assert sandbox_runner.clamp_timeout("abc") == 10.0


def test_sandbox_and_api_stay_in_sync() -> None:
    from sandbox import js_child

    assert js_child.WRAPPER == js_runner.WRAPPER
    assert sandbox_runner.ALLOWED_IMPORTS == code_runner.ALLOWED_IMPORTS
    assert sandbox_runner.python_child().is_file()


# ---------------- 서버(FastAPI) ----------------
def test_server_requires_key(sandbox_app: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"language": "python", "code": "result = {}", "inputs": {}}
    assert _post(sandbox_app, body, key=None).status_code == 401
    assert _post(sandbox_app, body, key="wrong").status_code == 401
    assert _post(sandbox_app, body, key=KEY[:-1]).status_code == 401  # 길이가 달라도 거절
    ok = _post(sandbox_app, body)
    assert ok.status_code == 200 and ok.json() == {"ok": True, "result": {}}
    # 키가 설정되지 않은 서버는 열어 두지 않고 거절한다
    monkeypatch.setenv("GENIO_SANDBOX_KEY", "")
    closed = _post(sandbox_app, body, key="")
    assert closed.status_code == 503 and closed.json()["kind"] == "config"


def test_server_health_and_no_docs(sandbox_app: TestClient) -> None:
    assert sandbox_app.get("/health").json() == {"status": "ok"}
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert sandbox_app.get(path).status_code == 404


def test_server_limits_and_validation(
    sandbox_app: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    huge = {"language": "python", "code": "result={}", "inputs": {"a": "x" * (1024 * 1024 + 10)}}
    assert _post(sandbox_app, huge).status_code == 413
    assert _post(sandbox_app, {"language": "ruby", "code": "x"}).status_code == 422
    assert _post(sandbox_app, {"language": "python"}).status_code == 422
    assert (
        _post(sandbox_app, {"language": "python", "code": "x", "timeout": 999}).status_code == 422
    )
    bad = sandbox_app.post("/run", content=b"not json", headers={"X-Sandbox-Key": KEY})
    assert bad.status_code == 422
    # 동시에 도는 코드가 너무 많으면 429
    import threading

    monkeypatch.setattr(sandbox_main, "_slots", threading.BoundedSemaphore(1))
    sandbox_main._slots.acquire()
    busy = _post(sandbox_app, {"language": "python", "code": "result={}"})
    assert busy.status_code == 429 and busy.json()["kind"] == "busy"
    sandbox_main._slots.release()
    assert _post(sandbox_app, {"language": "python", "code": "result={}"}).status_code == 200


def test_server_maps_timeout_and_errors(sandbox_app: TestClient) -> None:
    t = _post(sandbox_app, {"language": "python", "code": "while True:\n  pass", "timeout": 1})
    assert t.status_code == 200 and t.json()["kind"] == "timeout"
    e = _post(sandbox_app, {"language": "javascript", "code": "throw new Error('nope')"})
    assert e.status_code == 200 and e.json()["ok"] is False and "nope" in e.json()["error"]


# ---------------- 엔진 쪽 클라이언트 ----------------
Handler = Callable[[httpx.Request], httpx.Response]


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> list[dict[str, Any]]:
    """sandbox_client가 만드는 httpx.Client를 가짜 전송으로 바꾼다. 만들 때 받은 인자를 모아 돌려준다."""
    real = _REAL_CLIENT
    seen: list[dict[str, Any]] = []

    def factory(**kw: Any) -> httpx.Client:
        seen.append(kw)
        return real(transport=httpx.MockTransport(handler), timeout=kw.get("timeout"))

    monkeypatch.setattr(httpx, "Client", factory)
    return seen


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> None:
    st = get_settings()
    monkeypatch.setattr(st, "genio_sandbox_url", "http://sandbox:9100/")
    monkeypatch.setattr(st, "genio_sandbox_key", KEY)


def _json(data: Any, status: int = 200) -> Handler:
    return lambda req: httpx.Response(status, json=data)


def test_client_sends_key_payload_and_margin(monkeypatch: pytest.MonkeyPatch, remote: None) -> None:
    got: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        got["url"], got["key"], got["body"] = (
            str(req.url),
            req.headers["x-sandbox-key"],
            json.loads(req.content),
        )
        return httpx.Response(200, json={"ok": True, "result": {"a": 1}})

    seen = _mock_http(monkeypatch, handler)
    out = sandbox_client.run_remote("python", "result={'a':1}", {"n": 1}, 10)
    assert out == {"a": 1}
    assert got["url"] == "http://sandbox:9100/run" and got["key"] == KEY
    assert got["body"] == {
        "language": "python",
        "code": "result={'a':1}",
        "inputs": {"n": 1},
        "timeout": 10,
    }
    assert seen[0]["timeout"] == 10 + sandbox_client.MARGIN_SECONDS


@pytest.mark.parametrize(
    ("data", "expect"),
    [
        ({"ok": False, "kind": "timeout", "error": "x"}, "10초 안에 끝나지 않았어요"),
        ({"ok": False, "kind": "memory", "error": "x"}, "메모리를 너무 많이"),
        ({"ok": False, "kind": "output", "error": "x"}, "너무 커요"),
        ({"ok": False, "kind": "config", "error": "x"}, "GENIO_SANDBOX_KEY"),
        (
            {"ok": False, "kind": "error", "error": "ZeroDivisionError: x"},
            "코드 실행 중 오류: ZeroDivisionError",
        ),
    ],
)
def test_client_maps_error_kinds_to_two_lines(
    monkeypatch: pytest.MonkeyPatch, remote: None, data: dict[str, Any], expect: str
) -> None:
    _mock_http(monkeypatch, _json(data))
    with pytest.raises(NodeError) as exc:
        sandbox_client.run_remote("python", "x", {}, 10)
    assert expect in str(exc.value) and len(str(exc.value).split(". ")) >= 1
    assert "요" in str(exc.value)  # 어떻게 하면 되는지까지 한 문장 더


def test_client_javascript_error_text(monkeypatch: pytest.MonkeyPatch, remote: None) -> None:
    _mock_http(monkeypatch, _json({"ok": False, "kind": "error", "error": "boom"}))
    with pytest.raises(NodeError) as exc:
        sandbox_client.run_remote("javascript", "x", {}, 10)
    assert "자바스크립트 코드에서 오류가 났어요: boom" in str(exc.value)


@pytest.mark.parametrize(
    ("status", "expect"),
    [(401, "GENIO_SANDBOX_KEY"), (413, "1MB"), (429, "바빠요"), (500, "문제가 생겼어요")],
)
def test_client_http_statuses(
    monkeypatch: pytest.MonkeyPatch, remote: None, status: int, expect: str
) -> None:
    _mock_http(monkeypatch, _json({"ok": False}, status))
    with pytest.raises(NodeError) as exc:
        sandbox_client.run_remote("python", "x", {}, 10)
    assert expect in str(exc.value)
    assert KEY not in str(exc.value)


def test_client_unreachable_timeout_and_garbage(
    monkeypatch: pytest.MonkeyPatch, remote: None
) -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused http://sandbox:9100 key=" + KEY)

    _mock_http(monkeypatch, down)
    with pytest.raises(NodeError) as exc:
        sandbox_client.run_remote("python", "x", {}, 10)
    assert "연결하지 못했어요" in str(exc.value) and KEY not in str(exc.value)

    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    _mock_http(monkeypatch, slow)
    with pytest.raises(NodeError) as exc2:
        sandbox_client.run_remote("python", "x", {}, 10)
    assert "제때 답하지 않았어요" in str(exc2.value)

    _mock_http(monkeypatch, lambda req: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(NodeError) as exc3:
        sandbox_client.run_remote("python", "x", {}, 10)
    assert "답을 읽지 못했어요" in str(exc3.value)


# ---------------- 되돌림(기본은 서버 안 실행) ----------------
def test_default_stays_in_process() -> None:
    assert not sandbox_client.enabled()
    assert isinstance(code_runner.get_code_runner(), code_runner.RestrictedPythonRunner)
    with SessionLocal() as db:
        svc = RunServices(db, "ws")
        assert svc.run_code(code="result = {'v': inputs['n'] + 1}", inputs={"n": 1}) == {"v": 2}
        assert svc.run_code(
            code="result = {y: inputs.n * 2}", inputs={"n": 4}, language="javascript"
        ) == {"y": 8}


def test_enabled_routes_both_languages_to_sandbox(
    monkeypatch: pytest.MonkeyPatch, remote: None, sandbox_app: TestClient
) -> None:
    """클라이언트 → (가짜 전송) → 실제 샌드박스 앱까지 이어서 확인한다."""

    def forward(req: httpx.Request) -> httpx.Response:
        r = sandbox_app.post("/run", content=req.content, headers=dict(req.headers))
        return httpx.Response(r.status_code, content=r.content)

    _mock_http(monkeypatch, forward)
    assert isinstance(code_runner.get_code_runner(), code_runner.SandboxRunner)
    with SessionLocal() as db:
        svc = RunServices(db, "ws")
        assert svc.run_code(code="result = {'v': inputs['n'] + 1}", inputs={"n": 1}) == {"v": 2}
        assert svc.run_code(
            code="result = {y: inputs.n * 2}", inputs={"n": 4}, language="javascript"
        ) == {"y": 8}
        with pytest.raises(NodeError) as exc:
            svc.run_code(code="import os", inputs={})
        assert "코드 실행 중 오류" in str(exc.value)


# ---------------- 시스템 상태 항목 ----------------
def _sandbox_item() -> dict[str, Any]:
    with SessionLocal() as db:
        items = status_svc.system_status(db)["items"]
    return next(i for i in items if i["label"] == "코드 실행")


def test_status_item_in_process_then_ok_then_down(monkeypatch: pytest.MonkeyPatch) -> None:
    item = _sandbox_item()
    assert item["status"] == "unknown" and item["mode"] == "in-process"
    assert "격리 서버" in item["detail"]
    st = get_settings()
    monkeypatch.setattr(st, "genio_sandbox_url", "http://sandbox:9100")
    monkeypatch.setattr(sandbox_client, "health", lambda: (True, 12.0))
    ok = _sandbox_item()
    assert ok["status"] == "ok" and ok["mode"] == "sandbox" and "12" in ok["detail"]
    monkeypatch.setattr(sandbox_client, "health", lambda: (False, 2000.0))
    down = _sandbox_item()
    assert down["status"] == "error" and "응답하지 않아요" in down["detail"]


def test_health_helper_handles_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "genio_sandbox_url", "http://127.0.0.1:1")
    ok, ms = sandbox_client.health()
    assert ok is False and ms >= 0


# ---------------- Sentry ----------------
def test_sentry_scrubber_removes_pii_and_secrets() -> None:
    event: dict[str, Any] = {
        "user": {"id": "u1", "email": "a@b.com"},
        "server_name": "host-1",
        "request": {
            "url": "https://x/?api_key=abcd1234efgh",
            "headers": {"Authorization": "Bearer abcdefghijkl"},
            "cookies": {"s": "1"},
            "data": {"password": "hunter2hunter2"},
            "method": "POST",
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "failed with token=sk-abcdef123456 and Bearer abcdefghijklmnop",
                    "stacktrace": {"frames": [{"function": "f", "vars": {"key": "secret-value"}}]},
                }
            ]
        },
        "breadcrumbs": {"values": [{"message": "password=hunter2hunter2"}]},
        "message": "postgresql://user:pass1234@db/genio",
    }
    out = sentry_mod.scrub_event(event)
    text = str(out)
    assert "user" not in out and "server_name" not in out
    assert set(out["request"]) == {"method"}
    for secret in (
        "sk-abcdef123456",
        "abcdefghijklmnop",
        "hunter2hunter2",
        "pass1234",
        "secret-value",
    ):
        assert secret not in text
    assert "****" in text
    assert out["exception"]["values"][0]["type"] == "RuntimeError"


def test_sentry_breadcrumbs_drop_http() -> None:
    assert (
        sentry_mod.scrub_breadcrumb({"category": "httplib", "data": {"url": "https://x?k=1"}})
        is None
    )
    kept = sentry_mod.scrub_breadcrumb({"category": "query", "message": "token=abcdef123456"})
    assert kept is not None and "abcdef123456" not in str(kept)


def test_sentry_init_noop_without_dsn_and_safe_options_with_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sentry_sdk

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)
    assert sentry_mod.init_sentry("api") is False and calls == []
    st = get_settings()
    monkeypatch.setattr(st, "sentry_dsn", "https://pub@o0.ingest.sentry.io/1")
    monkeypatch.setattr(st, "sentry_traces_sample_rate", 5.0)
    monkeypatch.setattr(st, "genio_version", "abc123")
    assert sentry_mod.init_sentry("worker") is True
    kw = calls[0]
    assert kw["send_default_pii"] is False and kw["max_request_body_size"] == "never"
    assert kw["include_local_variables"] is False and kw["traces_sample_rate"] == 1.0
    assert kw["before_send"] is sentry_mod.scrub_event and kw["release"] == "abc123"
