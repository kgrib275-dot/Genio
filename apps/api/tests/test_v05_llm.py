"""v0.5 LLM·비용: Azure, 모델 카탈로그, 사람별 비용, 모델 교체 예상 비용, 월 한도·알림·보관 기간."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import openai
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.llm.base import LlmError
from api.llm.openai_adapter import OpenAIAdapter, azure_endpoint
from api.models import App, Conversation, Message, Run, Workspace
from api.services import limits
from api.tests.conftest import ROLES, Team, install


def _app(team: Team, name: str = "앱") -> str:
    with SessionLocal() as db:
        a = App(
            workspace_id=team.ws,
            name=name,
            slug=name,
            type="workflow",
            draft_graph={},
            created_by=team.users["builder"],
        )
        db.add(a)
        db.commit()
        return a.id


def _run(app_id: str, *, user: str | None, cost: str, tin: int, tout: int, **kw: Any) -> str:
    with SessionLocal() as db:
        r = Run(
            app_id=app_id,
            status=kw.get("status", "succeeded"),
            trigger=kw.get("trigger", "chat"),
            input={},
            created_by=user,
            cost=Decimal(cost),
            token_usage={"input_tokens": tin, "output_tokens": tout},
        )
        if "created_at" in kw:
            r.created_at = kw["created_at"]
        if "finished_at" in kw:
            r.finished_at = kw["finished_at"]
        if "error" in kw:
            r.error = kw["error"]
        db.add(r)
        db.commit()
        return r.id


# ---------------- Azure ----------------
def test_azure_endpoint_and_adapter() -> None:
    assert azure_endpoint("https://res.openai.azure.com/") == (
        "https://res.openai.azure.com/",
        "2024-10-21",
    )
    assert (
        azure_endpoint("https://res.openai.azure.com/openai?api-version=2025-01-01")[1]
        == "2025-01-01"
    )
    with pytest.raises(LlmError):
        azure_endpoint("http://plain.example.com")
    a = OpenAIAdapter("key-x", "https://res.openai.azure.com/", provider="azure")
    assert isinstance(a.client, openai.AzureOpenAI)


def test_add_azure_provider(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/llm-providers"
    base = {
        "provider": "azure",
        "label": "사내 Azure",
        "api_key": "azure-secret-key-777",
        "default_model": "gpt4o-deploy",
    }
    assert client.post(url, json=base, headers=team.h("owner")).status_code == 422
    assert (
        client.post(url, json={**base, "base_url": "ftp://x"}, headers=team.h("owner")).status_code
        == 422
    )
    res = client.post(
        url, json={**base, "base_url": "https://res.openai.azure.com/"}, headers=team.h("owner")
    )
    assert res.status_code == 200 and res.json()["provider"] == "azure"
    assert "azure-secret-key-777" not in res.text and res.json()["api_key_masked"].endswith("-777")


# ---------------- 카탈로그·사람별 비용·예상 비용 ----------------
def test_catalog(client: TestClient, team: Team) -> None:
    cat = client.get("/api/v1/llm/catalog", headers=team.h("member")).json()
    by = {m["model"]: m for m in cat}
    s = by["claude-sonnet-5-5"]
    assert s["provider"] == "anthropic" and s["input_price"] == 2.0 and s["tools"] is True
    assert by["text-embedding-3-small"]["embedding"] is True
    assert client.get("/api/v1/llm/catalog").status_code == 401


def test_usage_by_user_and_estimate(client: TestClient, team: Team) -> None:
    app_id = _app(team)
    _run(app_id, user=team.users["builder"], cost="0.50", tin=100_000, tout=10_000)
    _run(app_id, user=team.users["builder"], cost="0.25", tin=50_000, tout=5_000)
    _run(app_id, user=None, cost="0.10", tin=1_000, tout=1_000)
    u = client.get(
        f"/api/v1/workspaces/{team.ws}/usage?group=user", headers=team.h("operator")
    ).json()
    assert u["total_runs"] == 3 and abs(u["total_cost"] - 0.85) < 1e-9
    top = u["by_user"][0]
    assert (
        top["user_id"] == team.users["builder"]
        and top["runs"] == 2
        and abs(top["cost"] - 0.75) < 1e-9
    )
    assert any(x["user_id"] is None and x["name"] == "방문자·자동 실행" for x in u["by_user"])
    by_app = client.get(f"/api/v1/workspaces/{team.ws}/usage", headers=team.h("operator")).json()
    assert by_app["by_app"][0]["runs"] == 3

    est = client.get(
        f"/api/v1/workspaces/{team.ws}/usage/estimate?model=claude-haiku-5-5",
        headers=team.h("builder"),
    ).json()
    assert est["input_tokens"] == 151_000 and est["output_tokens"] == 16_000
    # 하이쿠: 0.10/0.50 per 1M → 0.0151 + 0.008
    assert abs(est["estimated_cost"] - 0.0231) < 1e-9 and est["difference"] < 0
    assert (
        client.get(
            f"/api/v1/workspaces/{team.ws}/usage/estimate?model=nope-1", headers=team.h("builder")
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{team.ws}/usage?group=user", headers=team.h("member")
        ).status_code
        == 403
    )


# ---------------- 월 한도·알림·보관 기간 ----------------
def test_limits_settings_and_budget(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/limits"
    for role in ROLES:
        code = client.get(url, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin") else 403), role
        code = client.patch(url, json={"monthly_budget_usd": 1}, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin") else 403), role
    assert client.patch(url, json={"retention_days": 1}, headers=team.h("owner")).status_code == 422
    assert (
        client.patch(url, json={"alert_emails": ["not-mail"]}, headers=team.h("owner")).status_code
        == 422
    )
    assert (
        client.patch(url, json={"alert_credential_id": "nope"}, headers=team.h("owner")).status_code
        == 422
    )
    got = client.patch(
        url, json={"monthly_budget_usd": 1.0, "retention_days": 30}, headers=team.h("owner")
    ).json()
    assert (
        got["monthly_budget_usd"] == 1.0
        and got["retention_days"] == 30
        and got["month_cost"] == 0.0
    )

    app_id = _app(team)
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        assert limits.check_run_allowed(db, app) is None
    _run(app_id, user=None, cost="1.20", tin=1, tout=1)
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        msg = limits.check_run_allowed(db, app)
        assert msg and "한도" in msg and "\n" in msg
    client.patch(url, json={"monthly_budget_usd": None}, headers=team.h("owner"))
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None and limits.check_run_allowed(db, app) is None


def test_alerts_send_failure_and_cost_mail(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(client, team, "email")
    cid = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={
            "connector_key": "email",
            "name": "알림 메일",
            "secrets": {
                "host": "smtp.example.com",
                "port": "587",
                "username": "u",
                "password": "p",
                "sender": "bot@example.com",
            },
        },
        headers=team.h("owner"),
    ).json()["id"]
    client.patch(
        f"/api/v1/workspaces/{team.ws}/limits",
        json={
            "alert_on_failure": True,
            "alert_emails": ["ops@example.com"],
            "alert_credential_id": cid,
            "cost_alert_usd": 0.5,
        },
        headers=team.h("owner"),
    )
    sent: list[dict[str, Any]] = []
    import api.connectors.runtime as rt

    def fake_run_connector(db: Any, ws: str, **kw: Any) -> dict[str, Any]:
        sent.append(kw)
        return {"sent": True}

    monkeypatch.setattr(rt, "run_connector", fake_run_connector)
    app_id = _app(team, "주문 처리")
    now = datetime.now(UTC)
    with SessionLocal() as db:
        limits.check_alerts(db, now - timedelta(seconds=1))  # 기준 시각 기록
    _run(
        app_id,
        user=None,
        cost="0.60",
        tin=1,
        tout=1,
        status="failed",
        trigger="webhook",
        error="상대 서버 오류",
        finished_at=now,
    )
    _run(
        app_id,
        user=None,
        cost="0",
        tin=1,
        tout=1,
        status="failed",
        trigger="test",
        error="테스트는 알리지 않음",
        finished_at=now,
    )
    with SessionLocal() as db:
        n = limits.check_alerts(db, now + timedelta(seconds=5))
    assert n == 2
    subjects = [s["params"]["subject"] for s in sent]
    assert any("실패 1건" in s for s in subjects) and any("비용" in s for s in subjects)
    assert all(s["params"]["to"] == "ops@example.com" and s["connector"] == "email" for s in sent)
    assert "테스트는 알리지 않음" not in str(sent)
    with SessionLocal() as db:  # 같은 달 비용 알림은 한 번만
        assert limits.check_alerts(db, now + timedelta(seconds=10)) == 0


def test_retention_removes_old_finished_runs_and_messages(client: TestClient, team: Team) -> None:
    client.patch(
        f"/api/v1/workspaces/{team.ws}/limits", json={"retention_days": 30}, headers=team.h("owner")
    )
    app_id = _app(team)
    old = datetime.now(UTC) - timedelta(days=40)
    old_run = _run(app_id, user=None, cost="0", tin=0, tout=0, created_at=old)
    waiting = _run(
        app_id, user=None, cost="0", tin=0, tout=0, created_at=old, status="waiting_approval"
    )
    fresh = _run(app_id, user=None, cost="0", tin=0, tout=0)
    with SessionLocal() as db:
        c_old = Conversation(
            app_id=app_id, external_session_id="s-old", variables={}, created_at=old
        )
        c_new = Conversation(app_id=app_id, external_session_id="s-new", variables={})
        db.add_all([c_old, c_new])
        db.flush()
        db.add_all(
            [
                Message(conversation_id=c_old.id, role="user", content="옛 질문", created_at=old),
                Message(conversation_id=c_new.id, role="user", content="새 질문"),
            ]
        )
        db.commit()
        removed = limits.apply_retention(db)
    assert removed["runs"] == 1 and removed["messages"] == 1 and removed["conversations"] == 1
    with SessionLocal() as db:
        left = set(db.scalars(select(Run.id).where(Run.app_id == app_id)))
        assert left == {waiting, fresh} and old_run not in left
        assert [m.content for m in db.scalars(select(Message))] == ["새 질문"]
        ws = db.get(Workspace, team.ws)
        assert ws is not None
