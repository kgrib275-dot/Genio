"""v0.9 서비스 이벤트 트리거: Slack·GitHub·Shopify·Telegram·Jira·Typeform.

서명 확인(알려진 값·틀린 값·오래된 시각), Slack 주소 확인, 이벤트 거르기, 값 연결, 재전송 무시,
샘플 시험, 비밀값 숨김, 역할별 권한.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.models import AppTrigger, Run
from api.services import service_events as sev
from api.tests.conftest import ROLES, Team
from api.tests.test_v04_triggers import make_app

GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {
            "id": "n1",
            "type": "input",
            "data": {
                "fields": [
                    {"key": "message", "type": "text"},
                    {"key": "title", "type": "text"},
                    {"key": "who", "type": "text"},
                ]
            },
        },
        {
            "id": "n2",
            "type": "output",
            "data": {"template": "{{n1.message}} | {{n1.title}} | {{n1.who}}"},
        },
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}

PROVIDER_SECRET = "provider-given-secret-0123456789"  # noqa: S105


@pytest.fixture(autouse=True)
def _fresh_seen() -> None:
    sev.reset_seen()


def hex_mac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def b64_mac(secret: str, msg: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()


def add_service(
    client: TestClient,
    team: Team,
    app_id: str,
    service: str,
    config: dict[str, Any] | None = None,
    role: str = "builder",
    secret: str | None = None,
) -> Any:
    body: dict[str, Any] = {
        "kind": "service",
        "config": {"service": service, **(config or {})},
    }
    if secret is not None:
        body["secret"] = secret
    return client.post(f"/api/v1/apps/{app_id}/triggers", json=body, headers=team.h(role))


def event_path(url: str) -> str:
    return url[url.index("/api/v1/events/") :]


def setup(
    client: TestClient,
    team: Team,
    service: str,
    config: dict[str, Any] | None = None,
) -> tuple[str, str, str, str]:
    """(app_id, trigger_id, 이벤트 주소, 서명에 쓸 비밀값)"""
    app_id = make_app(client, team, GRAPH)
    provider = sev.PRESETS[service].key_origin == "provider"
    res = add_service(
        client, team, app_id, service, config, secret=PROVIDER_SECRET if provider else None
    )
    assert res.status_code == 201, res.text
    t = res.json()
    secret = PROVIDER_SECRET if provider else t["secret"]
    return app_id, t["id"], event_path(t["url"]), secret


def gh_headers(
    secret: str, body: bytes, event: str = "issues", delivery: str = "d-1"
) -> dict[str, str]:
    return {
        "x-github-event": event,
        "x-github-delivery": delivery,
        "x-hub-signature-256": "sha256=" + hex_mac(secret, body),
        "content-type": "application/json",
    }


def gh_body(action: str = "opened", title: str = "로그인이 안 돼요") -> bytes:
    return json.dumps(
        {
            "action": action,
            "issue": {"title": title, "number": 3},
            "repository": {"full_name": "acme/app"},
            "sender": {"login": "hong"},
        },
        ensure_ascii=False,
    ).encode()


def runs_of(app_id: str) -> list[Run]:
    with SessionLocal() as db:
        return list(db.scalars(select(Run).where(Run.app_id == app_id).order_by(Run.created_at)))


# ---------------- 서명 확인(단위) ----------------
def test_github_documented_vector() -> None:
    """GitHub 문서의 공개 시험 값."""
    secret = "It's a Secret to Everybody"  # noqa: S105
    sig = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    assert sev.verify("github", secret, {"X-Hub-Signature-256": sig}, b"Hello, World!") is None
    assert sev.verify("github", secret, {"X-Hub-Signature-256": sig}, b"Hello, World?") is not None


def test_each_service_signature_valid_invalid() -> None:
    body = b'{"a": 1}'
    secret = "s3cret-value-xyz"  # noqa: S105
    ts = str(int(time.time()))
    valid: dict[str, dict[str, str]] = {
        "slack": {
            "x-slack-request-timestamp": ts,
            "x-slack-signature": "v0=" + hex_mac(secret, b"v0:" + ts.encode() + b":" + body),
        },
        "github": {"x-hub-signature-256": "sha256=" + hex_mac(secret, body)},
        "shopify": {"x-shopify-hmac-sha256": b64_mac(secret, body)},
        "telegram": {"x-telegram-bot-api-secret-token": secret},
        "typeform": {"typeform-signature": "sha256=" + b64_mac(secret, body)},
        "jira": {"x-hub-signature": "sha256=" + hex_mac(secret, body)},
    }
    for service, headers in valid.items():
        assert sev.verify(service, secret, headers, body) is None, service
        # 비밀값이 다르거나 본문이 바뀌면 거절, 헤더가 없어도 거절
        assert sev.verify(service, "other-secret", headers, body) is not None, service
        assert (
            sev.verify(service, secret, headers, body + b" ") is not None or service == "telegram"
        )
        assert sev.verify(service, secret, {}, body) is not None, service
    # Jira: 서명 대신 공유 비밀값(헤더·주소 뒤 ?secret=)도 된다
    assert sev.verify("jira", secret, {"x-genio-secret": secret}, body) is None
    assert sev.verify("jira", secret, {}, body, {"secret": secret}) is None
    assert sev.verify("jira", secret, {}, body, {"secret": "nope"}) is not None


def test_slack_expired_and_garbage_timestamp() -> None:
    body = b"{}"
    secret = "slack-signing-secret"  # noqa: S105
    old = str(int(time.time()) - 3600)
    sig = "v0=" + hex_mac(secret, b"v0:" + old.encode() + b":" + body)
    headers = {"x-slack-request-timestamp": old, "x-slack-signature": sig}
    assert "5분" in str(sev.verify("slack", secret, headers, body))
    assert sev.verify("slack", secret, {**headers, "x-slack-request-timestamp": "abc"}, body)
    # 시각을 맞춰 주면 같은 서명이어도 통과
    assert sev.verify("slack", secret, headers, body, now=float(old)) is None


# ---------------- 만들기·비밀값 ----------------
def test_create_returns_secret_once_and_hides_it(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    res = add_service(client, team, app_id, "github")
    assert res.status_code == 201, res.text
    t = res.json()
    assert t["kind"] == "service" and t["name"] == "GitHub 이벤트"
    assert "/api/v1/events/" in t["url"] and t["has_secret"] is True
    assert t["secret"].startswith("whsec_")
    # 목록·가져오기에는 비밀값 원문이 없다
    lst = client.get(f"/api/v1/apps/{app_id}/triggers", headers=team.h("builder")).json()
    assert all("secret" not in x for x in lst)
    assert t["secret"] not in json.dumps(lst)
    with SessionLocal() as db:
        row = db.get(AppTrigger, t["id"])
        assert row is not None and t["secret"] not in (row.secret_encrypted or "")


def test_provider_secret_required_and_never_echoed(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    r = add_service(client, team, app_id, "slack")
    assert r.status_code == 422
    assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]
    r = add_service(client, team, app_id, "slack", secret=PROVIDER_SECRET)
    assert r.status_code == 201 and r.json().get("secret") is None and r.json()["has_secret"]
    assert PROVIDER_SECRET not in r.text
    # 서비스가 정한 비밀값은 새로 만들지 않고, 붙여 넣은 값으로만 바꾼다
    tid = r.json()["id"]
    bad = client.post(f"/api/v1/triggers/{tid}/secret", headers=team.h("builder"))
    assert bad.status_code == 422
    ok = client.post(
        f"/api/v1/triggers/{tid}/secret",
        json={"secret": "another-provider-secret-1"},
        headers=team.h("builder"),
    )
    assert ok.status_code == 200 and ok.json()["secret"] is None


def test_config_validation(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    for cfg in (
        {"service": "nope"},
        {"service": "github", "events": ["push:weird"]},
        {"service": "github", "mapping": "text"},
    ):
        r = client.post(
            f"/api/v1/apps/{app_id}/triggers",
            json={"kind": "service", "config": cfg},
            headers=team.h("builder"),
        )
        assert r.status_code == 422, cfg
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]


def test_rotate_generated_secret_invalidates_old(client: TestClient, team: Team) -> None:
    app_id, tid, path, secret = setup(client, team, "github")
    body = gh_body()
    ok = client.post(path, content=body, headers=gh_headers(secret, body))
    assert ok.status_code == 202, ok.text
    new = client.post(f"/api/v1/triggers/{tid}/secret", headers=team.h("builder")).json()["secret"]
    assert new != secret
    old = client.post(path, content=body, headers=gh_headers(secret, body, delivery="d-2"))
    assert old.status_code == 401
    good = client.post(path, content=body, headers=gh_headers(new, body, delivery="d-3"))
    assert good.status_code == 202
    assert len(runs_of(app_id)) == 2


# ---------------- 받기(GitHub) ----------------
def test_github_event_runs_flow_with_mapping(client: TestClient, team: Team) -> None:
    app_id, tid, path, secret = setup(
        client,
        team,
        "github",
        {"events": ["issues:opened"], "mapping": {"title": "issue.title", "who": "sender.login"}},
    )
    body = gh_body()
    res = client.post(path, content=body, headers=gh_headers(secret, body))
    assert res.status_code == 202, res.text
    runs = runs_of(app_id)
    assert len(runs) == 1 and runs[0].trigger == "service"
    assert runs[0].input["title"] == "로그인이 안 돼요" and runs[0].input["who"] == "hong"
    assert "이슈 opened" in runs[0].input["message"] and runs[0].input["service"] == "github"
    assert runs[0].status == "succeeded"
    assert "로그인이 안 돼요 | hong" in str((runs[0].output or {}).get("text"))
    # 마지막 상태가 트리거에 남는다
    with SessionLocal() as db:
        row = db.get(AppTrigger, tid)
        assert row is not None and row.last_run_id == runs[0].id


def test_github_event_filter_ping_and_dedupe(client: TestClient, team: Team) -> None:
    app_id, tid, path, secret = setup(client, team, "github", {"events": ["issues:opened"]})
    # 고르지 않은 이벤트(닫힘), 연결 확인(ping)은 실행을 만들지 않는다
    closed = gh_body("closed")
    r = client.post(path, content=closed, headers=gh_headers(secret, closed, delivery="d-closed"))
    assert r.status_code == 200 and "ignored" in r.json()
    ping = b'{"zen": "Keep it logically awesome."}'
    r = client.post(
        path, content=ping, headers=gh_headers(secret, ping, event="ping", delivery="d-p")
    )
    assert r.status_code == 200 and "ignored" in r.json()
    assert runs_of(app_id) == []
    # 같은 알림(delivery id)이 다시 오면 한 번만 실행
    body = gh_body()
    h = gh_headers(secret, body, delivery="same-1")
    assert client.post(path, content=body, headers=h).status_code == 202
    again = client.post(path, content=body, headers=h)
    assert again.status_code == 200 and "이미 받은" in again.json()["ignored"]
    assert len(runs_of(app_id)) == 1
    # 최근 받은 값에 걸러낸 것도 이유와 함께 보인다(서명 헤더는 빠져 있다)
    pl = client.get(f"/api/v1/triggers/{tid}/payloads", headers=team.h("builder")).json()
    assert any("걸러냄" in (p.get("note") or "") for p in pl)
    assert all("x-hub-signature-256" not in p["headers"] for p in pl)


def test_bad_signature_json_size_and_unknown_token(client: TestClient, team: Team) -> None:
    app_id, tid, path, secret = setup(client, team, "github")
    body = gh_body()
    bad = client.post(path, content=body, headers=gh_headers("wrong-secret-value", body))
    assert bad.status_code == 401
    d = bad.json()["detail"]
    assert d["message"] and d["hint"] and secret not in json.dumps(d)
    pl = client.get(f"/api/v1/triggers/{tid}/payloads", headers=team.h("builder")).json()
    assert pl and pl[0]["accepted"] is False
    # JSON이 아니면 400, 너무 크면 413, 모르는 주소는 404
    raw = b"not json"
    assert client.post(path, content=raw, headers=gh_headers(secret, raw)).status_code == 400
    big = b"x" * (256 * 1024 + 1)
    assert client.post(path, content=big, headers=gh_headers(secret, big)).status_code == 413
    assert client.post("/api/v1/events/no-such-token", content=body).status_code == 404
    client.patch(f"/api/v1/triggers/{tid}", json={"enabled": False}, headers=team.h("builder"))
    assert client.post(path, content=body, headers=gh_headers(secret, body)).status_code == 404
    assert runs_of(app_id) == []


def test_rate_limit_per_trigger(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.core import ratelimit

    _, _, path, secret = setup(client, team, "github")
    monkeypatch.setattr(ratelimit, "allow", lambda *a, **k: False)
    body = gh_body()
    r = client.post(path, content=body, headers=gh_headers(secret, body))
    assert r.status_code == 429 and r.json()["detail"]["hint"]


# ---------------- Slack ----------------
def slack_headers(secret: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    stamp = str(ts if ts is not None else int(time.time()))
    return {
        "x-slack-request-timestamp": stamp,
        "x-slack-signature": "v0=" + hex_mac(secret, b"v0:" + stamp.encode() + b":" + body),
        "content-type": "application/json",
    }


def test_slack_challenge_bot_filter_and_types(client: TestClient, team: Team) -> None:
    app_id, tid, path, secret = setup(
        client, team, "slack", {"events": ["message"], "mapping": {"who": "event.user"}}
    )
    ch = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    r = client.post(path, content=ch, headers=slack_headers(secret, ch))
    assert r.status_code == 200 and r.json() == {"challenge": "abc123"}
    assert runs_of(app_id) == []
    # 서명이 틀리면 확인 요청도 거절한다
    assert (
        client.post(path, content=ch, headers=slack_headers("wrong-secret-xx", ch)).status_code
        == 401
    )
    # 오래된 서명(다시 보내기 공격)
    old = slack_headers(secret, ch, ts=int(time.time()) - 3600)
    assert client.post(path, content=ch, headers=old).status_code == 401

    def ev(kind: str = "message", **extra: Any) -> bytes:
        inner = {"type": kind, "user": "U1", "text": "배송 문의", "channel": "C1", **extra}
        return json.dumps(
            {"type": "event_callback", "event_id": f"Ev-{kind}-{len(extra)}", "event": inner}
        ).encode()

    body = ev()
    assert client.post(path, content=body, headers=slack_headers(secret, body)).status_code == 202
    assert (
        runs_of(app_id)[0].input["who"] == "U1"
        and "배송 문의" in runs_of(app_id)[0].input["message"]
    )
    # 봇 메시지는 기본으로 건너뛴다. @멘션은 고른 이벤트가 아니라 건너뛴다.
    bot = ev(bot_id="B1")
    r = client.post(path, content=bot, headers=slack_headers(secret, bot))
    assert r.status_code == 200 and "봇" in r.json()["ignored"]
    men = ev("app_mention")
    assert client.post(path, content=men, headers=slack_headers(secret, men)).json()["ignored"]
    assert len(runs_of(app_id)) == 1
    # 봇 메시지도 받도록 바꾸면 실행된다
    client.patch(
        f"/api/v1/triggers/{tid}",
        json={"config": {"include_bot": True}},
        headers=team.h("builder"),
    )
    bot2 = ev(bot_id="B2")
    assert client.post(path, content=bot2, headers=slack_headers(secret, bot2)).status_code == 202


def test_slack_challenge_without_secret_only_answers(client: TestClient, team: Team) -> None:
    app_id, tid, path, _ = setup(client, team, "slack")
    with SessionLocal() as db:
        row = db.get(AppTrigger, tid)
        assert row is not None
        row.secret_encrypted = None
        db.commit()
    ch = json.dumps({"type": "url_verification", "challenge": "zzz"}).encode()
    assert client.post(path, content=ch).json() == {"challenge": "zzz"}
    event = json.dumps(
        {"type": "event_callback", "event": {"type": "message", "text": "hi"}}
    ).encode()
    assert client.post(path, content=event).status_code == 401
    assert runs_of(app_id) == []


# ---------------- 나머지 서비스 ----------------
def test_shopify_telegram_jira_typeform_end_to_end(client: TestClient, team: Team) -> None:
    # Shopify
    app_id, _, path, secret = setup(client, team, "shopify", {"events": ["orders/create"]})
    body = json.dumps(sev.PRESETS["shopify"].sample_body).encode()
    h = {
        "x-shopify-topic": "orders/create",
        "x-shopify-webhook-id": "w1",
        "x-shopify-hmac-sha256": b64_mac(secret, body),
    }
    assert client.post(path, content=body, headers=h).status_code == 202
    assert "주문" in runs_of(app_id)[0].input["message"]
    other = {**h, "x-shopify-topic": "customers/create", "x-shopify-webhook-id": "w2"}
    assert client.post(path, content=body, headers=other).json()["ignored"]
    # Telegram
    app_id, _, path, secret = setup(
        client, team, "telegram", {"mapping": {"who": "message.from.first_name"}}
    )
    body = json.dumps(sev.PRESETS["telegram"].sample_body, ensure_ascii=False).encode()
    h = {"x-telegram-bot-api-secret-token": secret}
    assert client.post(path, content=body, headers=h).status_code == 202
    assert (
        runs_of(app_id)[0].input["who"] == "길동"
        and "회의실" in runs_of(app_id)[0].input["message"]
    )
    assert (
        client.post(
            path, content=body, headers={"x-telegram-bot-api-secret-token": "x" * 12}
        ).status_code
        == 401
    )
    # Jira: 주소 뒤 ?secret=
    app_id, _, path, secret = setup(client, team, "jira", {"events": ["jira:issue_created"]})
    body = json.dumps(sev.PRESETS["jira"].sample_body, ensure_ascii=False).encode()
    assert client.post(path, content=body).status_code == 401
    assert client.post(f"{path}?secret={secret}", content=body).status_code == 202
    assert "OPS-17" in runs_of(app_id)[0].input["message"]
    # Typeform
    app_id, _, path, secret = setup(
        client, team, "typeform", {"mapping": {"who": "form_response.answers[0].text"}}
    )
    body = json.dumps(sev.PRESETS["typeform"].sample_body, ensure_ascii=False).encode()
    h = {"typeform-signature": "sha256=" + b64_mac(secret, body)}
    assert client.post(path, content=body, headers=h).status_code == 202
    assert runs_of(app_id)[0].input["who"] == "홍길동"


# ---------------- 샘플 시험·값 연결 ----------------
def test_sample_test_runs_with_mapping(client: TestClient, team: Team) -> None:
    app_id, tid, _, _ = setup(
        client, team, "github", {"mapping": {"title": "issue.title", "who": "sender.login"}}
    )
    res = client.post(f"/api/v1/triggers/{tid}/test-sample", headers=team.h("builder"))
    assert res.status_code == 201, res.text
    d = res.json()
    assert d["input"]["title"] == "로그인 화면이 열리지 않아요" and d["input"]["who"] == "hong"
    assert d["run"]["trigger"] == "service"
    assert runs_of(app_id)[0].status == "succeeded"
    pl = client.get(f"/api/v1/triggers/{tid}/payloads", headers=team.h("builder")).json()
    assert pl[0]["note"] == "샘플로 시험"
    # 서비스 이벤트가 아닌 트리거는 샘플 시험을 쓸 수 없다
    wh = client.post(
        f"/api/v1/apps/{app_id}/triggers",
        json={"kind": "webhook", "config": {}},
        headers=team.h("builder"),
    ).json()
    assert (
        client.post(
            f"/api/v1/triggers/{wh['id']}/test-sample", headers=team.h("builder")
        ).status_code
        == 409
    )


def test_get_path_and_build_input() -> None:
    data = {"a": {"b": [{"c": 5}, {"c": "x"}]}, "t": "글"}
    assert sev.get_path(data, "a.b[0].c") == 5
    assert sev.get_path(data, "a.b[-1].c") == "x"
    assert sev.get_path(data, "a.b[9].c") is None
    assert sev.get_path(data, "a.zzz") is None
    ev = sev.ParsedEvent(name="x", label="라벨", summary="요약")
    out = sev.build_input("github", ev, data, {"k1": "t", "k2": "a.b", "k3": "none.path"})
    assert out["message"] == "요약" and out["k1"] == "글" and out["k3"] == ""
    assert json.loads(out["k2"])[0] == {"c": 5}  # 목록·묶음은 글(JSON)로


# ---------------- 권한 ----------------
def test_permissions_per_role(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    for role in ROLES:
        r = client.get(f"/api/v1/apps/{app_id}/service-presets", headers=team.h(role))
        assert r.status_code == (200 if role in ("owner", "admin", "builder") else 403), role
        c = add_service(client, team, app_id, "github", role=role)
        assert c.status_code == (201 if role in ("owner", "admin", "builder") else 403), role
    tid = add_service(client, team, app_id, "github").json()["id"]
    for role in ("operator", "member"):
        assert (
            client.post(f"/api/v1/triggers/{tid}/test-sample", headers=team.h(role)).status_code
            == 403
        )
        assert (
            client.post(f"/api/v1/triggers/{tid}/secret", headers=team.h(role)).status_code == 403
        )
        assert (
            client.get(f"/api/v1/triggers/{tid}/payloads", headers=team.h(role)).status_code == 403
        )
    # 보기만 하는 운영자에게는 받는 주소(비밀)를 숨긴다
    res = client.get(f"/api/v1/apps/{app_id}/triggers", headers=team.h("operator"))
    assert res.status_code == 200 and all(t["url"] is None for t in res.json())
    presets = client.get(f"/api/v1/apps/{app_id}/service-presets", headers=team.h("builder")).json()
    assert {p["key"] for p in presets} == {
        "slack",
        "github",
        "shopify",
        "telegram",
        "jira",
        "typeform",
    }
    assert all(p["instructions"] and p["events"] and p["sample"]["body"] for p in presets)
