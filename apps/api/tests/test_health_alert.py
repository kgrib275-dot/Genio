"""서비스 이상 알림: 오류 항목만 알리고, 중복을 막고, 복구를 알린다."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import SessionLocal
from api.engine import safe_http
from api.services import health_alert, mailer, status
from api.tests.conftest import Team


def report(*items: tuple[str, str, str]) -> dict[str, Any]:
    return {"items": [{"status": s, "label": label, "detail": d} for s, label, d in items]}


@pytest.fixture
def box(monkeypatch: pytest.MonkeyPatch, client: TestClient, team: Team) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    monkeypatch.setattr(mailer, "OUTBOX", out)
    r = client.put(
        "/api/v1/admin/system/mail",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "noreply",
            "password": "pw-secret-1234",
            "from_addr": "noreply@example.com",
            "security": "starttls",
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text
    health_alert._memory.clear()
    return out


def run(rep: dict[str, Any], now: float) -> dict[str, Any]:
    with SessionLocal() as db:
        return health_alert.check(db, now=now)


def test_problems_picks_errors_and_backup_warnings() -> None:
    rep = report(
        ("ok", "DB", ""),
        ("error", "Redis", "연결 안 됨"),
        ("warn", "대기 중인 작업", "많음"),
        ("warn", "DB 백업", "오래됨"),
        ("unknown", "예약 실행", ""),
    )
    assert health_alert.problems(rep) == {"Redis": "연결 안 됨", "DB 백업": "오래됨"}


def test_alert_once_repeat_after_six_hours_and_recovery(
    monkeypatch: pytest.MonkeyPatch, box: list[dict[str, str]]
) -> None:
    current = {"rep": report(("error", "실행 워커", "응답이 없어요"))}
    monkeypatch.setattr(status, "system_status", lambda db: current["rep"])
    t0 = 1_000_000.0

    first = run(current["rep"], t0)
    assert first["alerted"] == ["실행 워커"] and len(box) == 1
    assert "응답이 없어요" in box[0]["text"] and box[0]["to"] == "owner@test.local"

    # 같은 문제는 6시간 안에는 다시 알리지 않는다
    assert run(current["rep"], t0 + 3600)["alerted"] == []
    assert len(box) == 1
    # 6시간이 지나면 한 번 더
    assert run(current["rep"], t0 + 6 * 3600 + 1)["alerted"] == ["실행 워커"]
    assert len(box) == 2

    # 좋아지면 복구를 알린다(한 번만)
    current["rep"] = report(("ok", "실행 워커", ""))
    out = run(current["rep"], t0 + 7 * 3600)
    assert out["recovered"] == ["실행 워커"] and len(box) == 3
    assert "복구" in box[2]["subject"]
    assert run(current["rep"], t0 + 8 * 3600)["recovered"] == [] and len(box) == 3


def test_new_problem_alerts_immediately_and_webhook(
    monkeypatch: pytest.MonkeyPatch, box: list[dict[str, str]]
) -> None:
    rep = {"rep": report(("error", "DB", "연결 못 함"))}
    monkeypatch.setattr(status, "system_status", lambda db: rep["rep"])
    calls: list[tuple[str, Any]] = []

    def fake(method: str, url: str, **kw: Any) -> dict[str, Any]:
        calls.append((url, kw.get("body")))
        return {"status": 200}

    monkeypatch.setattr(safe_http, "request", fake)
    monkeypatch.setattr(get_settings(), "genio_alert_webhook_url", "https://hooks.example.com/x")
    run(rep["rep"], 5_000_000.0)
    assert calls and calls[0][0] == "https://hooks.example.com/x"
    assert "DB" in calls[0][1]["text"]
    # 다른 항목이 새로 나빠지면 그것만 바로 알린다
    rep["rep"] = report(("error", "DB", "연결 못 함"), ("error", "Redis", "끊김"))
    out = run(rep["rep"], 5_000_000.0 + 300)
    assert out["alerted"] == ["Redis"]


def test_no_mail_settings_does_not_break_the_check(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, team: Team
) -> None:
    health_alert._memory.clear()
    monkeypatch.setattr(mailer, "OUTBOX", None)
    monkeypatch.setattr(status, "system_status", lambda db: report(("error", "DB", "x")))
    out = run({}, 1.0)  # 메일 설정이 없어도 예외 없이 끝난다
    assert out["alerted"] == ["DB"]
