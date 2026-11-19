"""사용성 개선 묶음(ops4) 시험: 배포 시 자동 저장 등."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import Team, install


def _new_app(client: TestClient, team: Team) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "자동 저장"}, headers=team.h("builder")
    )
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def test_deploy_without_version_saves_draft_first(client: TestClient, team: Team) -> None:
    app_id = _new_app(client, team)
    assert client.get(f"/api/v1/apps/{app_id}/versions", headers=team.h("builder")).json() == []
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "workspace"},
        headers=team.h("admin"),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["auto_saved"] is True and body["version"] == 1
    versions = client.get(f"/api/v1/apps/{app_id}/versions", headers=team.h("builder")).json()
    assert [v["version"] for v in versions] == [1]
    # 두 번째 배포는 새 버전을 만들지 않는다
    again = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "workspace"},
        headers=team.h("admin"),
    )
    assert again.json()["auto_saved"] is False
    assert len(client.get(f"/api/v1/apps/{app_id}/versions", headers=team.h("builder")).json()) == 1


def test_deploy_with_invalid_draft_explains_instead_of_saving(
    client: TestClient, team: Team
) -> None:
    app_id = _new_app(client, team)
    bad = {"version": 1, "nodes": [], "edges": [], "variables": {}}
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": bad}, headers=team.h("builder"))
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "workspace"},
        headers=team.h("admin"),
    )
    assert res.status_code == 422
    assert client.get(f"/api/v1/apps/{app_id}/versions", headers=team.h("builder")).json() == []


def test_chatbot_from_knowledge_base(client: TestClient, team: Team) -> None:
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "휴가 규정"},
        headers=team.h("builder"),
    ).json()
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/chatbot", json={}, headers=team.h("builder")
    )
    assert res.status_code == 201, res.text
    app = res.json()
    assert app["name"] == "휴가 규정 챗봇" and app["type"] == "chat"
    assert app["latest_version"] == 1
    nodes = {n["type"]: n for n in app["draft_graph"]["nodes"]}
    assert nodes["knowledge_search"]["data"]["kb_id"] == kb["id"]
    assert app["features"]["citations"]["enabled"] is True
    v = client.post(f"/api/v1/apps/{app['id']}/validate", json={}, headers=team.h("builder")).json()
    assert v["valid"] is True, str(v["errors"])
    # 운영자는 만들 수 없고, 없는 지식베이스는 404
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/chatbot", json={}, headers=team.h("operator")
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/knowledge-bases/none/chatbot", json={}, headers=team.h("builder")
        ).status_code
        == 404
    )


def test_improvements_collect_dislikes_and_no_answers(client: TestClient, team: Team) -> None:
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    # 같은 질문을 두 번 싫어요, 다른 질문은 좋아요(모음에 안 들어간다)
    for _ in range(2):
        ev = chat(client, token, "재택근무는 며칠까지 돼요?")
        mid = next(d for n, d in ev if n == "answer")["message_id"]
        client.post(
            f"/api/v1/public/apps/{token}/messages/{mid}/feedback",
            json={"rating": "dislike", "comment": "틀렸어요"},
        )
    ok = chat(client, token, "연차는 며칠이에요?")
    client.post(
        f"/api/v1/public/apps/{token}/messages/{next(d for n, d in ok if n == 'answer')['message_id']}/feedback",
        json={"rating": "like"},
    )
    res = client.get(f"/api/v1/apps/{app_id}/improvements", headers=team.h("builder")).json()
    assert res["open_count"] == 1
    item = res["items"][0]
    assert item["count"] == 2 and item["reason"] == "dislike" and item["comment"] == "틀렸어요"
    assert "재택근무" in item["question"]
    # 운영자는 볼 수 없다
    assert (
        client.get(f"/api/v1/apps/{app_id}/improvements", headers=team.h("operator")).status_code
        == 403
    )
    # 고친 답을 모범 답변으로 등록하면 같은 질문 모음이 한 번에 사라진다
    r = client.post(
        f"/api/v1/apps/{app_id}/improvements/{item['message_id']}/answer",
        json={"answer": "재택은 주 2일까지예요."},
        headers=team.h("builder"),
    )
    assert r.status_code == 201, r.text
    after = client.get(f"/api/v1/apps/{app_id}/improvements", headers=team.h("builder")).json()
    assert after["open_count"] == 0
    anns = client.get(f"/api/v1/apps/{app_id}/annotations", headers=team.h("builder")).json()
    assert [a["answer"] for a in anns] == ["재택은 주 2일까지예요."]


def test_improvements_dismiss(client: TestClient, team: Team) -> None:
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    ev = chat(client, token, "이건 괜찮은 질문")
    mid = next(d for n, d in ev if n == "answer")["message_id"]
    client.post(f"/api/v1/public/apps/{token}/messages/{mid}/feedback", json={"rating": "dislike"})
    items = client.get(f"/api/v1/apps/{app_id}/improvements", headers=team.h("builder")).json()
    assert items["open_count"] == 1
    d = client.post(
        f"/api/v1/apps/{app_id}/improvements/{items['items'][0]['message_id']}/dismiss",
        headers=team.h("builder"),
    )
    assert d.json() == {"dismissed": 1}
    assert (
        client.get(f"/api/v1/apps/{app_id}/improvements", headers=team.h("builder")).json()[
            "open_count"
        ]
        == 0
    )
    # 다른 앱의 답변 번호로는 처리할 수 없다
    other = faq_app(client, team)
    assert (
        client.post(
            f"/api/v1/apps/{other}/improvements/{mid}/dismiss", headers=team.h("builder")
        ).status_code
        == 404
    )


def test_dry_run_connector_previews_instead_of_sending(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.db import SessionLocal
    from api.engine import executor
    from api.engine.executor import RunServices, is_read_action

    sent: list[str] = []

    def fake_run(*_a: object, **kw: object) -> dict[str, object]:
        sent.append(str(kw.get("action")))
        return {"ok": True}

    monkeypatch.setattr(executor, "run_connector", fake_run)
    with SessionLocal() as db:
        svc = RunServices(db, team.ws)
        svc.dry_run = True
        out = svc.run_connector(
            connector="slack", credential_id="c", action="post_message", params={"text": "안녕"}
        )
        assert (
            out["dry_run"] is True and out["sent"] is False and out["preview"] == {"text": "안녕"}
        )
        assert sent == []
        # 읽기 동작은 시험 모드에서도 그대로 실행한다
        assert svc.run_connector(
            connector="slack", credential_id="c", action="list_channels", params={}
        ) == {"ok": True}
        # 시험 모드가 아니면 보낸다
        svc.dry_run = False
        svc.run_connector(connector="slack", credential_id="c", action="post_message", params={})
        assert sent == ["list_channels", "post_message"]
    assert is_read_action("get_row") and not is_read_action("send_email")


def test_run_api_accepts_dry_run_and_keeps_it_in_context(client: TestClient, team: Team) -> None:
    app_id = _new_app(client, team)
    res = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "안녕"}, "dry_run": True},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    run = client.get(f"/api/v1/runs/{res.json()['id']}", headers=team.h("builder")).json()
    assert run["status"] == "succeeded"


def _email_credential(client: TestClient, team: Team) -> str:
    install(client, team, "email")
    return str(
        client.post(
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
    )


def test_budget_warning_at_80_percent_and_monthly_report(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    import api.connectors.runtime as rt
    from api.db import SessionLocal
    from api.models import App, Run
    from api.services import limits

    cid = _email_credential(client, team)
    res = client.patch(
        f"/api/v1/workspaces/{team.ws}/limits",
        json={
            "monthly_budget_usd": 10,
            "monthly_report": True,
            "alert_emails": ["boss@example.com"],
            "alert_credential_id": cid,
        },
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["monthly_report"] is True
    sent: list[dict[str, object]] = []

    def fake(db: object, ws: str, **kw: object) -> dict[str, bool]:
        sent.append(kw)
        return {"sent": True}

    monkeypatch.setattr(rt, "run_connector", fake)
    now = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    last_month = now - timedelta(days=5)
    with SessionLocal() as db:
        a = App(
            workspace_id=team.ws,
            name="휴가 챗봇",
            slug="leave",
            type="chat",
            draft_graph={},
            created_by=team.users["builder"],
            features={"time_saved": {"minutes_per_run": 6}},
        )
        db.add(a)
        db.flush()
        for _ in range(10):
            db.add(
                Run(
                    app_id=a.id,
                    status="succeeded",
                    trigger="chat",
                    input={},
                    cost=Decimal("0.85"),
                    created_at=last_month,
                )
            )
        # 이번 달(12월) 비용이 월 한도의 80%를 넘음
        db.add(
            Run(
                app_id=a.id,
                status="succeeded",
                trigger="chat",
                input={},
                cost=Decimal("8.5"),
                created_at=now - timedelta(hours=1),
            )
        )
        db.commit()
    with SessionLocal() as db:
        n = limits.check_alerts(db, now)
    subjects = [str(s["params"]["subject"]) for s in sent]  # type: ignore[index]
    assert (
        n == 2
        and any("80%" in s for s in subjects)
        and any("11월 이용 요약" in s for s in subjects)
    )
    report = next(s for s in sent if "이용 요약" in str(s["params"]["subject"]))  # type: ignore[index]
    body = str(report["params"]["body"])  # type: ignore[index]
    assert "성공한 실행: 10건" in body and "약 1.0시간" in body and "휴가 챗봇" in body
    # 같은 달에는 다시 보내지 않는다
    with SessionLocal() as db:
        assert limits.check_alerts(db, now + timedelta(minutes=5)) == 0


def test_app_digest_counts_today_and_failure_reasons(client: TestClient, team: Team) -> None:
    from datetime import UTC, datetime

    from api.db import SessionLocal
    from api.models import Run

    app_id = _new_app(client, team)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for _ in range(3):
            db.add(Run(app_id=app_id, status="succeeded", trigger="chat", input={}, created_at=now))
        for _ in range(2):
            db.add(
                Run(
                    app_id=app_id,
                    status="failed",
                    trigger="chat",
                    input={},
                    error="상대 서버가 응답하지 않았어요.\n자세한 내용",
                    created_at=now,
                )
            )
        # 시험 실행은 세지 않는다
        db.add(Run(app_id=app_id, status="failed", trigger="test", input={}, created_at=now))
        db.commit()
    res = client.get(f"/api/v1/apps/{app_id}/digest", headers=team.h("operator")).json()
    assert res["today"] == {"succeeded": 3, "failed": 2, "total": 5}
    assert res["headline"] == "오늘 3건 처리, 2건 실패"
    assert res["failure_reasons"] == [{"reason": "상대 서버가 응답하지 않았어요.", "count": 2}]
    # 멤버(운영자보다 아래)는 볼 수 없다
    assert client.get(f"/api/v1/apps/{app_id}/digest", headers=team.h("member")).status_code == 403


def test_transfer_member_assets(client: TestClient, team: Team) -> None:
    from api.db import SessionLocal
    from api.models import App

    app_id = _new_app(client, team)  # builder가 만든 앱
    owner = team.users["owner"]
    builder = team.users["builder"]
    base = f"/api/v1/workspaces/{team.ws}/members"
    info = client.get(f"{base}/{builder}/assets", headers=team.h("admin")).json()
    assert [a["id"] for a in info["apps"]] == [app_id]
    # 운영자·제작자는 인수인계를 할 수 없다
    assert (
        client.post(
            f"{base}/{builder}/transfer", json={"to_user_id": owner}, headers=team.h("builder")
        ).status_code
        == 403
    )
    # 앱을 만들 수 없는 역할에게는 넘기지 못한다
    bad = client.post(
        f"{base}/{builder}/transfer",
        json={"to_user_id": team.users["operator"]},
        headers=team.h("admin"),
    )
    assert bad.status_code == 422
    assert (
        client.post(
            f"{base}/{builder}/transfer", json={"to_user_id": builder}, headers=team.h("admin")
        ).status_code
        == 422
    )
    ok = client.post(
        f"{base}/{builder}/transfer", json={"to_user_id": owner}, headers=team.h("admin")
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["apps"] == 1
    with SessionLocal() as db:
        assert db.get(App, app_id).created_by == owner  # type: ignore[union-attr]
    assert client.get(f"{base}/{builder}/assets", headers=team.h("admin")).json()["apps"] == []
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).json()
    assert any(entry["action"] == "member.transfer_assets" for entry in logs)


def test_uploaded_document_reports_personal_info(
    client: TestClient, team: Team, fake_llm: object
) -> None:
    from api.tests.conftest import add_llm

    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "직원 명부"},
        headers=team.h("builder"),
    ).json()
    text = "김하나 연락처 010-1234-5678, 주민번호 900101-1234567.\n연차는 15일입니다."
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("명부.txt", text.encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    docs = client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=team.h("builder")
    ).json()
    row = next(d for d in docs if d["id"] == doc["id"])
    assert row["status"] == "ready"
    assert row["pii"]["주민등록번호"] == 1 and len(row["pii"]) >= 2
    assert "_pii" not in row["metadata"]
    clean = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("규정.txt", "연차는 15일입니다.".encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    docs = client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=team.h("builder")
    ).json()
    assert next(d for d in docs if d["id"] == clean["id"])["pii"] is None


def test_maintenance_mode_blocks_public_chat_but_still_shows_page(
    client: TestClient, team: Team
) -> None:
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    assert chat(client, token, "안녕")  # 평소에는 답한다
    res = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"maintenance": {"enabled": True, "message": "오후 3시까지 고치는 중이에요."}},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    info = client.get(f"/api/v1/public/apps/{token}").json()
    assert info["maintenance"] == {"enabled": True, "message": "오후 3시까지 고치는 중이에요."}
    blocked = client.post(f"/api/v1/public/apps/{token}/chat", json={"message": "안녕"})
    assert blocked.status_code == 503
    detail = blocked.json()["detail"]
    assert "점검 중" in detail["message"] and "오후 3시" in detail["hint"]
    # 끄면 다시 답한다
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"maintenance": {"enabled": False}},
        headers=team.h("builder"),
    )
    assert chat(client, token, "안녕")
    assert client.get(f"/api/v1/public/apps/{token}").json()["maintenance"]["enabled"] is False


def _signed_slack(secret: str, body: str, ts: float | None = None) -> dict[str, str]:
    import time

    from api.services import messenger as m

    stamp = str(int(ts if ts is not None else time.time()))
    return {
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": m.slack_signature(secret, stamp, body.encode()),
        "content-type": "application/x-www-form-urlencoded",
    }


def test_slack_slash_command_answers_via_response_url(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import urlencode

    from api.routers import messenger as router_mod
    from api.tests.test_v02_features import deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    base = f"/api/v1/public/messenger/{token}/slack"
    assert client.get(f"/api/v1/apps/{app_id}/messenger", headers=team.h("builder")).json()[
        "slack"
    ] == {"configured": False, "hint": ""}
    form = urlencode(
        {
            "text": "연차는 며칠이에요?",
            "user_id": "U1",
            "team_id": "T1",
            "response_url": "https://hooks.slack.com/commands/T1/1/abc",
        }
    )
    # 연결하기 전에는 있는지도 알려 주지 않는다
    assert client.post(base, content=form, headers=_signed_slack("x" * 12, form)).status_code == 404
    # 설정: 제작자만, 짧은 비밀값은 거절
    put = f"/api/v1/apps/{app_id}/messenger/slack"
    assert client.put(put, json={"secret": "abc"}, headers=team.h("builder")).status_code == 422
    assert (
        client.put(put, json={"secret": "s3cret-signing"}, headers=team.h("operator")).status_code
        == 403
    )
    ok = client.put(put, json={"secret": "s3cret-signing"}, headers=team.h("builder"))
    assert ok.status_code == 200, ok.text
    info = ok.json()
    assert info["slack"]["configured"] is True and "s3cret-signing" not in str(info)
    assert info["slack_url"].endswith(f"/public/messenger/{token}/slack")
    # 서명이 틀리거나 오래되면 거절
    assert (
        client.post(base, content=form, headers=_signed_slack("wrong-secret", form)).status_code
        == 401
    )
    old = client.post(base, content=form, headers=_signed_slack("s3cret-signing", form, ts=1))
    assert old.status_code == 401
    # 맞는 서명: 바로 '찾는 중'을 돌려주고, 답은 response_url로 보낸다
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(router_mod, "_post_slack", lambda url, text: sent.append((url, text)))
    res = client.post(base, content=form, headers=_signed_slack("s3cret-signing", form))
    assert res.status_code == 200, res.text
    assert res.json()["response_type"] == "ephemeral" and "찾아보는 중" in res.json()["text"]
    assert len(sent) == 1 and sent[0][0].startswith("https://hooks.slack.com/")
    assert "연차는 며칠이에요?" in sent[0][1]  # 에코 앱이라 질문이 그대로 돌아온다
    # 빈 질문은 사용법을 알려 준다
    empty = urlencode({"text": "  ", "response_url": "https://hooks.slack.com/x"})
    r2 = client.post(base, content=empty, headers=_signed_slack("s3cret-signing", empty))
    assert "궁금한 것" in r2.json()["text"]
    # 연결 끊기
    assert client.delete(put, headers=team.h("builder")).json()["slack"]["configured"] is False
    assert (
        client.post(base, content=form, headers=_signed_slack("s3cret-signing", form)).status_code
        == 404
    )


def test_teams_outgoing_webhook_answers_inline_and_checks_hmac(
    client: TestClient, team: Team
) -> None:
    import base64
    import json

    from api.services import messenger as m
    from api.tests.test_v02_features import deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    secret = base64.b64encode(b"teams-shared-secret-bytes").decode()
    client.put(
        f"/api/v1/apps/{app_id}/messenger/teams", json={"secret": secret}, headers=team.h("builder")
    )
    url = f"/api/v1/public/messenger/{token}/teams"
    body = json.dumps(
        {
            "type": "message",
            "text": "<at>제니오</at> 재택은 며칠?",
            "from": {"id": "u1"},
            "conversation": {"id": "c1"},
        }
    ).encode()
    bad = client.post(url, content=body, headers={"authorization": "HMAC AAAA"})
    assert bad.status_code == 401
    good = client.post(
        url, content=body, headers={"authorization": m.teams_signature(secret, body)}
    )
    assert good.status_code == 200, good.text
    out = good.json()
    assert out["type"] == "message" and "재택은 며칠?" in out["text"] and "<at>" not in out["text"]


def test_messenger_helpers() -> None:
    from api.services import messenger as m

    assert m.clean_question("<at>제니오</at>&nbsp; 안녕하세요 <b>!</b>") == "안녕하세요 !"
    assert m.valid_slack_response_url("https://hooks.slack.com/commands/a")
    assert not m.valid_slack_response_url("https://evil.example.com/x")
    assert not m.valid_slack_response_url("http://hooks.slack.com/x")
    sig = m.slack_signature("secret-123", "1000", b"a=b")
    assert m.verify_slack("secret-123", "1000", sig, b"a=b", now=1100)
    assert not m.verify_slack("secret-123", "1000", sig, b"a=c", now=1100)
    assert not m.verify_slack("secret-123", "1000", sig, b"a=b", now=5000)


def test_messenger_status_without_deployment_is_not_an_error(
    client: TestClient, team: Team
) -> None:
    app_id = _new_app(client, team)
    res = client.get(f"/api/v1/apps/{app_id}/messenger", headers=team.h("builder"))
    assert res.status_code == 200 and res.json() == {"deployed": False}
    # 설정은 배포한 뒤에만 된다
    put = client.put(
        f"/api/v1/apps/{app_id}/messenger/slack",
        json={"secret": "s3cret-signing"},
        headers=team.h("builder"),
    )
    assert put.status_code == 409


def test_production_detection_and_required_keys() -> None:
    from api.config import Settings, fernet_key_problem, is_production

    secret = "x" * 40
    assert not is_production(
        Settings(
            genio_env="dev", genio_public_web_url="http://localhost:5190", genio_secret_key=secret
        )
    )
    assert is_production(Settings(genio_env="prod", genio_secret_key=secret))
    # GENIO_ENV를 dev로 둔 채 공개 주소를 쓰면 운영으로 본다
    assert is_production(
        Settings(
            genio_env="dev",
            genio_public_web_url="https://genio.example.com",
            genio_secret_key=secret,
        )
    )
    assert fernet_key_problem(Settings(genio_fernet_key="", genio_secret_key=secret))
    assert fernet_key_problem(Settings(genio_fernet_key="k" * 44, genio_secret_key=secret)) is None


def test_dry_run_blocks_http_writes_mcp_and_api_tools_but_not_reads(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.db import SessionLocal
    from api.engine.executor import RunServices, is_read_action

    calls: list[str] = []

    def fake_request(method: str, url: str, **kw: object) -> dict[str, object]:
        calls.append(f"{method} {url}")
        return {"status": 200, "headers": {}, "body": {"ok": True}}

    monkeypatch.setattr("api.engine.safe_http.request", fake_request)
    with SessionLocal() as db:
        svc = RunServices(db, team.ws)
        svc.dry_run = True
        out = svc.http_request(
            method="POST", url="https://hooks.example.com/x", headers={}, body={"text": "안녕"}
        )
        assert out["body"]["dry_run"] is True and out["body"]["preview"] == {"text": "안녕"}
        assert calls == []
        # 읽기(GET)는 그대로 나간다
        svc.http_request(method="GET", url="https://api.example.com/v1", headers={}, body=None)
        assert calls == ["GET https://api.example.com/v1"]
        assert (
            svc.mcp_call(credential_id="c", tool="send_message", arguments={"a": 1})["sent"]
            is False
        )
        assert (
            svc.api_tool_call(tool_set_id="t", operation="createOrder", params={}, body={})["sent"]
            is False
        )
        svc.dry_run = False
        svc.http_request(method="DELETE", url="https://api.example.com/v1/1", headers={}, body=None)
        assert calls[-1] == "DELETE https://api.example.com/v1/1"
    # 이름이 읽기로 시작해도 쓰기 낱말이 들어 있으면 읽기가 아니다
    assert not is_read_action("find_and_replace") and not is_read_action("fetch_and_send")
    assert is_read_action("get_row") and is_read_action("getUser")


def test_dry_run_follows_into_child_app_runs(client: TestClient, team: Team) -> None:
    from sqlalchemy import select

    from api.db import SessionLocal
    from api.engine.agent import run_child_app
    from api.engine.executor import RunServices
    from api.models import Run, WorkflowVersion

    child = _new_app(client, team)
    client.post(f"/api/v1/apps/{child}/versions", json={}, headers=team.h("builder"))
    with SessionLocal() as db:
        svc = RunServices(db, team.ws)
        svc.dry_run = True
        run_child_app(svc, child, {"message": "hi"})
        run = db.scalars(select(Run).where(Run.app_id == child, Run.trigger == "tool")).one()
        assert (run.context or {}).get("dry_run") is True
        assert db.scalar(select(WorkflowVersion).where(WorkflowVersion.app_id == child)) is not None


def test_messenger_hardening(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import urlencode

    from api.core import ratelimit
    from api.routers import messenger as router_mod
    from api.services import messenger as m
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    put = f"/api/v1/apps/{app_id}/messenger/slack"
    assert (
        client.put(put, json={"secret": "s3cret-signing"}, headers=team.h("builder")).status_code
        == 200
    )
    base = f"/api/v1/public/messenger/{token}/slack"
    sent: list[str] = []
    monkeypatch.setattr(router_mod, "_post_slack", lambda url, text: sent.append(text))
    form = urlencode(
        {
            "text": "연차?",
            "user_id": "U1",
            "team_id": "T1",
            "trigger_id": "t-1",
            "response_url": "https://hooks.slack.com/commands/T1/1/abc",
        }
    )
    hdr = _signed_slack("s3cret-signing", form)
    assert client.post(base, content=form, headers=hdr).status_code == 200
    # 같은 요청이 다시 오면(슬랙 재시도·재전송) 다시 답하지 않는다
    again = client.post(base, content=form, headers=hdr)
    assert "이미" in again.json()["text"] and len(sent) == 1
    # 비ASCII 서명 헤더는 500이 아니라 401
    bad: dict[str, Any] = {
        **_signed_slack("s3cret-signing", form + "x"),
        "x-slack-signature": b"v0=" + bytes([0xE9]),
    }
    assert client.post(base, content=form + "x", headers=bad).status_code == 401
    # 서명이 틀린 요청이 많아도 앱 단위 제한을 쓰지 않아 정상 요청은 막히지 않는다
    for i in range(10):
        client.post(base, content=f"a={i}", headers=_signed_slack("wrong-secret", f"a={i}"))
    form2 = urlencode(
        {
            "text": "재택?",
            "user_id": "U2",
            "team_id": "T1",
            "trigger_id": "t-2",
            "response_url": "https://hooks.slack.com/commands/T1/2/abc",
        }
    )
    assert (
        client.post(base, content=form2, headers=_signed_slack("s3cret-signing", form2)).status_code
        == 200
    )
    # 슬랙 대화 이름은 서버만 만든다: 공개 챗에서 slack: 세션 이름은 거절
    res = client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "안녕", "session_id": "slack:T1:U1"}
    )
    assert res.status_code == 422
    assert m.session_key("slack", "a" * 12, "T:U") != m.session_key("slack", "b" * 12, "T:U")
    assert chat(client, token, "안녕")
    # 배포 모양을 저장해도 연결이 끊기지 않는다
    dep_id = client.get(f"/api/v1/apps/{app_id}/deployments", headers=team.h("builder")).json()[0][
        "id"
    ]
    r = client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"title": "새 제목"}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/apps/{app_id}/messenger", headers=team.h("builder")).json()[
        "slack"
    ]["configured"]
    # 공개 범위가 제한된 배포는 연결·사용 모두 거절
    client.patch(
        f"/api/v1/deployments/{dep_id}", json={"access": "workspace"}, headers=team.h("builder")
    )
    closed = client.post(
        base, content=form2 + "&z=1", headers=_signed_slack("s3cret-signing", form2 + "&z=1")
    )
    assert "공개 범위가 제한" in closed.json()["text"]
    assert (
        client.put(put, json={"secret": "another-secret"}, headers=team.h("builder")).status_code
        == 422
    )
    ratelimit.reset()


# ---------------- 동시성 안전장치 ----------------
def test_run_claim_is_atomic_and_stale_runs_do_not_restart(client: TestClient, team: Team) -> None:
    from sqlalchemy import select

    from api.db import SessionLocal
    from api.engine.executor import _claim, _execute
    from api.models import Run, RunStep

    app_id = _new_app(client, team)
    with SessionLocal() as db:
        run = Run(app_id=app_id, trigger="api", status="queued", input={"message": "hi"})
        db.add(run)
        db.commit()
        run_id = run.id
    with SessionLocal() as a, SessionLocal() as b:
        ra, rb = a.get(Run, run_id), b.get(Run, run_id)
        assert ra is not None and rb is not None
        assert _claim(a, ra, "queued", started=True) is True
        # 두 번째 워커는 이미 잡힌 실행을 잡지 못한다
        assert _claim(b, rb, "queued", started=True) is False
    with SessionLocal() as db:
        # 이미 running인 실행이 다시 전달돼도 처음부터 다시 돌지 않는다
        _execute(db, run_id)
        assert db.scalars(select(RunStep).where(RunStep.run_id == run_id)).all() == []
        assert db.get(Run, run_id).status == "running"  # type: ignore[union-attr]


def test_task_decision_is_claimed_once(client: TestClient, team: Team) -> None:
    from api.core.errors import AppError
    from api.db import SessionLocal
    from api.models import HumanTask, User
    from api.services import tasks as tasks_svc

    app_id = _new_app(client, team)
    with SessionLocal() as db:
        t = HumanTask(
            workspace_id=team.ws,
            app_id=app_id,
            kind="approval",
            title="승인",
            detail="",
            fields=[],
            status="open",
            token="tok-claim-1",  # noqa: S106
        )
        db.add(t)
        db.commit()
        tid = t.id
    with SessionLocal() as a, SessionLocal() as b:
        ta, tb = a.get(HumanTask, tid), b.get(HumanTask, tid)  # 둘 다 열린 상태로 읽음
        assert ta is not None and tb is not None and ta.status == tb.status == "open"
        user = a.get(User, team.users["admin"])
        tasks_svc.complete(a, ta, approved=True, values={}, comment="", user=user, via="app")
        with pytest.raises(AppError) as exc:
            tasks_svc.complete(b, tb, approved=False, values={}, comment="", user=user, via="app")
        assert exc.value.status == 409
    with SessionLocal() as db:
        assert (db.get(HumanTask, tid).response or {}).get("approved") is True  # type: ignore[union-attr]


def test_integrity_conflict_becomes_korean_409() -> None:
    from fastapi import FastAPI
    from sqlalchemy.exc import IntegrityError

    from api.core.errors import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    res = TestClient(app).get("/boom")
    assert res.status_code == 409
    body = res.json()["detail"]
    assert "겹쳐" in body["message"] and "새로고침" in body["hint"]


def test_stuck_run_sweeper_requeues_and_fails(client: TestClient, team: Team) -> None:
    from datetime import UTC, datetime, timedelta

    from api.db import SessionLocal
    from api.models import Run
    from api.services import run_sweeper

    app_id = _new_app(client, team)
    now = datetime.now(UTC)
    old = now - timedelta(minutes=30)
    with SessionLocal() as db:
        queued = Run(app_id=app_id, trigger="api", status="queued", input={}, created_at=old)
        fresh = Run(app_id=app_id, trigger="api", status="queued", input={}, created_at=now)
        waiting = Run(
            app_id=app_id,
            trigger="api",
            status="queued",
            input={},
            created_at=old,
            context={"capacity_wait": {"since": now.isoformat()}},
        )
        stuck = Run(
            app_id=app_id, trigger="api", status="running", input={}, started_at=old, created_at=old
        )
        ok = Run(
            app_id=app_id, trigger="api", status="running", input={}, started_at=now, created_at=now
        )
        db.add_all([queued, fresh, waiting, stuck, ok])
        db.commit()
        ids = {
            "queued": queued.id,
            "fresh": fresh.id,
            "waiting": waiting.id,
            "stuck": stuck.id,
            "ok": ok.id,
        }
    with SessionLocal() as db:
        res = run_sweeper.sweep(db, now)
    assert res["requeued"] == [ids["queued"]] and res["failed"] == [ids["stuck"]]
    with SessionLocal() as db:
        assert db.get(Run, ids["stuck"]).status == "failed"  # type: ignore[union-attr]
        assert "서버가 멈춰서" in (db.get(Run, ids["stuck"]).error or "")  # type: ignore[union-attr]
        assert db.get(Run, ids["ok"]).status == "running"  # type: ignore[union-attr]
        # 같은 실행을 5분 안에 또 넣지 않고, 세 번을 넘기면 실패로 끝낸다
        assert run_sweeper.sweep(db, now + timedelta(minutes=1))["requeued"] == []
        later = now
        for _ in range(run_sweeper.MAX_REQUEUES - 1):
            later += timedelta(minutes=6)
            run_sweeper.sweep(db, later)
        later += timedelta(minutes=6)
        assert ids["queued"] in run_sweeper.sweep(db, later)["failed"]


def test_enqueue_failure_does_not_break_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.config import get_settings
    from api.services import queue

    class Broken:
        def send_task(self, *a: object, **k: object) -> None:
            raise ConnectionError("redis down")

    monkeypatch.setattr(get_settings(), "genio_run_inline", False)
    monkeypatch.setattr(queue, "_client", lambda: Broken())
    queue.enqueue_run("r1")  # 예외 없이 지나간다(대기 상태로 남아 점검이 다시 넣는다)
    queue.enqueue_run("r1", countdown=5)


def test_document_processing_is_claimed_once(client: TestClient, team: Team) -> None:
    from api.db import SessionLocal
    from api.models import Document, KnowledgeBase
    from api.services import knowledge

    with SessionLocal() as db:
        kb = KnowledgeBase(workspace_id=team.ws, name="동시", embedding_model="m")
        db.add(kb)
        db.flush()
        doc = Document(
            kb_id=kb.id,
            filename="a.txt",
            mime="text/plain",
            size=3,
            status="processing",
            content=b"abc",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
        knowledge.process_document(db, doc_id)  # 다른 워커가 처리 중이면 건드리지 않는다
        assert db.get(Document, doc_id).status == "processing"  # type: ignore[union-attr]


def test_alert_failure_in_one_workspace_does_not_stop_others(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.db import SessionLocal
    from api.services import limits

    seen: list[str] = []

    def fake(ws_id: str, n: object) -> int:
        seen.append(ws_id)
        if len(seen) == 1:
            raise RuntimeError("메일 서버 오류")
        return 1

    monkeypatch.setattr(limits, "_check_workspace", fake)
    with SessionLocal() as db:
        from api.models import Organization, Workspace

        org = Organization(name="o2", slug="o2-slug")
        db.add(org)
        db.flush()
        db.add(Workspace(org_id=org.id, name="둘째", slug="second"))
        db.commit()
        assert limits.check_alerts(db) == 1
    assert len(seen) >= 2


def test_builder_blocks_second_message_while_first_is_pending(
    client: TestClient, team: Team
) -> None:
    from api.db import SessionLocal
    from api.models import BuilderMessage
    from api.tests.test_builder import new_session

    _, sid = new_session(client, team, "동시 대화")
    with SessionLocal() as db:
        db.add(BuilderMessage(session_id=sid, role="user", content="앞 요청"))
        db.commit()
    res = client.post(
        f"/api/v1/builder/sessions/{sid}/messages",
        json={"content": "또 요청"},
        headers=team.h("builder"),
    )
    assert res.status_code == 409
    assert "답하는 중" in res.json()["detail"]["message"]


def test_improvement_answer_is_idempotent(client: TestClient, team: Team) -> None:
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    mid = next(d for n, d in chat(client, token, "재택은?") if n == "answer")["message_id"]
    client.post(f"/api/v1/public/apps/{token}/messages/{mid}/feedback", json={"rating": "dislike"})
    url = f"/api/v1/apps/{app_id}/improvements/{mid}/answer"
    first = client.post(url, json={"answer": "주 2일"}, headers=team.h("builder")).json()
    second = client.post(url, json={"answer": "주 2일"}, headers=team.h("builder")).json()
    assert first["annotation_id"] == second["annotation_id"]
    anns = client.get(f"/api/v1/apps/{app_id}/annotations", headers=team.h("builder")).json()
    assert len(anns) == 1


# ---------------- 인증·입력 방어 ----------------
def test_totp_code_cannot_be_replayed_and_password_checks_are_limited(
    client: TestClient, team: Team
) -> None:
    from api.core import ratelimit, totp

    ratelimit.reset()
    h = team.h("operator")
    secret = client.post("/api/v1/me/2fa/setup", headers=h).json()["secret"]
    client.post("/api/v1/me/2fa/enable", json={"code": totp.totp(secret)}, headers=h)

    def login() -> str:
        return str(
            client.post(
                "/api/v1/auth/login",
                json={"email": "operator@test.local", "password": "password123!"},
            )
            .json()
            .get("mfa_token", "")
        )

    code = totp.totp(secret)
    first = client.post("/api/v1/auth/login/mfa", json={"mfa_token": login(), "code": code})
    again = client.post("/api/v1/auth/login/mfa", json={"mfa_token": login(), "code": code})
    assert first.status_code == 200
    assert again.status_code == 401  # 같은 코드를 엿봐서 다시 써도 받지 않는다
    # 비밀번호 확인 API는 계속 틀려 볼 수 없다
    ratelimit.reset()
    for _ in range(5):
        r = client.post(
            "/api/v1/me/password",
            json={"current_password": "wrong-password-1", "new_password": "NewPassw0rd!x"},
            headers=h,
        )
        assert r.status_code == 400
    blocked = client.post(
        "/api/v1/me/password",
        json={"current_password": "wrong-password-1", "new_password": "NewPassw0rd!x"},
        headers=h,
    )
    assert blocked.status_code == 429 and "15분" in blocked.json()["detail"]["hint"]
    ratelimit.reset()


def test_signup_is_rate_limited_per_address(client: TestClient) -> None:
    from api.core import ratelimit

    ratelimit.reset()
    codes = []
    for i in range(12):
        res = client.post(
            "/api/v1/auth/signup",
            json={
                "email": f"bulk{i}@example.com",
                "password": "Passw0rd!test",
                "name": "대량",
                "workspace_name": f"팀{i}",
                "agree_terms": True,
                "agree_privacy": True,
            },
        )
        codes.append(res.status_code)
    assert 429 in codes and codes[0] in (200, 201)
    ratelimit.reset()


def test_template_blocks_memory_bombs_but_keeps_normal_use() -> None:
    from api.engine.templating import TemplateRenderError, render

    assert render("{{ name }}님 {{ 2 * 3 }} {{ '-' * 3 }}", {"name": "하나"}) == "하나님 6 ---"
    for bomb in ("{{ 'a' * 100000000 }}", "{{ 9 ** 99999 }}", "{{ [0] * 99999999 }}"):
        with pytest.raises(TemplateRenderError):
            render(bomb, {})
    with pytest.raises(TemplateRenderError):
        render("{% for i in range(5000) %}{{ 'x' * 1000 }}{% endfor %}", {})


def test_webhook_rejects_oversized_declared_body(client: TestClient) -> None:
    res = client.post("/api/v1/hooks/nothing", content=b"x" * (1_048_576 + 10))
    assert res.status_code == 413


def test_daily_limit_caps_public_chat(client: TestClient, team: Team) -> None:
    from api.tests.test_v02_features import chat, deploy, faq_app

    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    res = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"daily_limit": {"per_day": 2}},
        headers=team.h("builder"),
    )
    assert res.json()["features"]["daily_limit"]["per_day"] == 2
    assert chat(client, token, "하나") and chat(client, token, "둘")
    third = client.post(f"/api/v1/public/apps/{token}/chat", json={"message": "셋"})
    assert third.status_code == 429 and "내일" in third.json()["detail"]["hint"]
    # 상한을 끄면(0) 다시 받는다
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"daily_limit": {"per_day": 0}},
        headers=team.h("builder"),
    )
    assert chat(client, token, "넷")
