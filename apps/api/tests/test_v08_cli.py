"""명령줄 도구(scripts/genio_cli.py): 키 찾기, 입력 파싱, 요청 모양, 오류 두 줄, JSON 출력."""

import importlib.util
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "genio_cli.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("genio_cli", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load()


class FakeRes:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeRes":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class Recorder:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload, self.error, self.calls = payload, error, []  # type: ignore[var-annotated]

    def __call__(self, req: Any, timeout: float = 0) -> FakeRes:
        self.calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "auth": req.get_header("Authorization"),
                "body": json.loads(req.data.decode("utf-8")) if req.data else None,
            }
        )
        if self.error:
            raise self.error
        return FakeRes(self.payload)


def _run(argv: list[str], rec: Recorder, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, opener=rec, out=out, err=err, env=env or {})
    return code, out.getvalue(), err.getvalue()


def test_parse_inputs() -> None:
    assert cli.parse_inputs(
        ["city=도쿄", "days:=3", "vip:=true", 'tags:=["a","b"]', "memo=a=b"]
    ) == {
        "city": "도쿄",
        "days": 3,
        "vip": True,
        "tags": ["a", "b"],
        "memo": "a=b",
    }
    for bad in ("novalue", "=x", "n:={bad"):
        with pytest.raises(cli.CliError):
            cli.parse_inputs([bad])


def test_run_sends_inputs_and_prints_result() -> None:
    rec = Recorder(
        {
            "run_id": "r1",
            "status": "succeeded",
            "outputs": {"text": "안녕 김"},
            "error": None,
            "elapsed_ms": 12,
        }
    )
    code, out, err = _run(
        ["run", "-i", "name=김", "-i", "n:=2", "--url", "https://g.example.com/"],
        rec,
        {"GENIO_API_KEY": "gk-env"},
    )
    assert code == 0 and err == "" and "상태: succeeded" in out and "안녕 김" in out
    call = rec.calls[0]
    assert call["url"] == "https://g.example.com/api/v1/service/workflows/run"
    assert call["method"] == "POST" and call["auth"] == "Bearer gk-env"
    assert call["body"] == {"inputs": {"name": "김", "n": 2}}


def test_key_as_first_positional_and_chat() -> None:
    rec = Recorder({"answer": "연차는 15일이에요.", "conversation_id": "c-9"})
    code, out, _ = _run(["chat", "gk-abc", "연차", "며칠이야?", "-c", "c-1"], rec)
    assert code == 0 and "연차는 15일이에요." in out and "c-9" in out
    assert rec.calls[0]["auth"] == "Bearer gk-abc"
    assert rec.calls[0]["body"] == {
        "query": "연차 며칠이야?",
        "inputs": {},
        "conversation_id": "c-1",
    }
    assert rec.calls[0]["url"] == "http://127.0.0.1:5190/api/v1/service/chat-messages"


def test_info_runs_and_run_status() -> None:
    info = {
        "app": {"name": "휴가 봇", "type": "chat"},
        "version": 3,
        "input_fields": [{"key": "message", "label": "문의", "type": "text", "required": True}],
    }
    code, out, _ = _run(["info", "--key", "gk-x"], Recorder(info))
    assert code == 0 and "휴가 봇" in out and "입력 message" in out and "(필수)" in out
    runs = [{"run_id": "r1", "status": "failed", "created_at": "2026-11-05", "error": "시간 초과"}]
    rec = Recorder(runs)
    code, out, _ = _run(["runs", "--key", "gk-x", "--limit", "500", "--status", "failed"], rec)
    assert code == 0 and "r1" in out and "시간 초과" in out
    assert rec.calls[0]["url"].endswith("/service/runs?limit=100&status=failed")
    rec2 = Recorder(
        {"status": "succeeded", "trigger": "api", "outputs": {"text": "끝"}, "error": None}
    )
    code, out, _ = _run(["run-status", "gk-x", "r1"], rec2)
    assert code == 0 and "끝" in out and rec2.calls[0]["url"].endswith("/service/runs/r1")


def test_json_flag() -> None:
    code, out, _ = _run(
        ["run", "--key", "gk-x", "--json"],
        Recorder({"run_id": "r", "status": "ok", "outputs": {}, "error": None, "elapsed_ms": 1}),
    )
    assert code == 0 and json.loads(out)["run_id"] == "r"


def test_errors_are_two_lines_and_codes() -> None:
    code, _, err = _run(["info"], Recorder({}))  # 키 없음
    assert code == 2 and len(err.strip().splitlines()) == 2 and "GENIO_API_KEY" in err
    http = urllib.error.HTTPError(
        "u",
        403,
        "x",
        Message(),
        io.BytesIO(
            json.dumps(
                {"detail": {"message": "권한이 없어요.", "hint": "키를 새로 만드세요."}}
            ).encode()
        ),
    )
    code, _, err = _run(["run", "--key", "gk-x"], Recorder(error=http))
    assert code == 1 and err.strip().splitlines() == ["권한이 없어요.", "키를 새로 만드세요."]
    code, _, err = _run(["run", "--key", "gk-x"], Recorder(error=urllib.error.URLError("down")))
    assert code == 1 and "접속하지 못했어요" in err and len(err.strip().splitlines()) == 2
    code, _, err = _run(["chat", "--key", "gk-x"], Recorder({}))  # 메시지 없음
    assert code == 2 and "메시지" in err
    code, _, err = _run(["info", "--key", "gk-x", "--url", "ftp://x"], Recorder({}))
    assert code == 2 and "올바르지" in err
    assert _run(["bogus"], Recorder({}))[0] == 2
