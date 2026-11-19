"""사용성 개선 묶음(ops4) 시험: 배포 시 자동 저장 등."""

from __future__ import annotations

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
