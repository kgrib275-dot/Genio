"""마켓(설치·번들 검증·단계 등록), 배포·공개 챗(접근 규칙·속도 제한·위젯), 지식베이스, 인증."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.core import ratelimit
from api.market.bundle import BundleError, validate_bundle
from api.services.knowledge import chunk_text
from api.tests.conftest import Team, add_llm, install
from api.tests.fakes import FakeAdapter
from nodes import registry


# ---------------- 마켓 ----------------
def test_catalog_has_design_items(client: TestClient, team: Team) -> None:
    items = client.get("/api/v1/market/items", headers=team.h("member")).json()
    by_type: dict[str, list[str]] = {}
    for i in items:
        by_type.setdefault(i["type"], []).append(i["key"])
    # 설계서 기본 3종 + v0.5(DB·HTTP 인증·잔디·네이버웍스·카카오 알림톡)
    assert {"email", "google_sheets", "slack"} <= set(by_type["connector"])
    assert {"database", "http_credentials", "jandi", "naverworks", "kakao_alimtalk"} <= set(
        by_type["connector"]
    )
    # 템플릿 5 + 업무 단위 템플릿 5(S10) + v0.6 템플릿 11 + v0.8 템플릿 3
    assert len(by_type["template"]) == 24
    assert len(by_type["prompt_pack"]) == 9
    assert by_type["node"] == ["node_text_tools"]
    found = client.get("/api/v1/market/items?q=슬랙", headers=team.h("member")).json()
    assert {"slack", "tpl_inquiry_router"} <= {i["key"] for i in found}


def test_install_connector_and_paid_item(client: TestClient, team: Team) -> None:
    install(client, team, "slack")
    defs = client.get(
        f"/api/v1/workspaces/{team.ws}/connectors/definitions", headers=team.h("member")
    ).json()
    assert [d["key"] for d in defs] == ["slack"]
    install(client, team, "prompts_office")  # 유료(1000) → mock 결제
    packs = client.get(
        f"/api/v1/workspaces/{team.ws}/prompt-packs", headers=team.h("builder")
    ).json()
    assert packs[0]["prompts"][0]["title"] == "회의록 정리"
    items = client.get(
        f"/api/v1/market/items?workspace_id={team.ws}", headers=team.h("builder")
    ).json()
    assert {i["key"] for i in items if i["installed"]} == {"slack", "prompts_office"}
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).json()
    assert any(
        entry["action"] == "market.install" and entry["meta"]["price"] == 1000 for entry in logs
    )
    # 개수 제한(limit): 1~1000
    one = client.get(
        f"/api/v1/workspaces/{team.ws}/audit-logs?limit=1", headers=team.h("owner")
    ).json()
    assert len(one) == 1 and one[0]["id"] == logs[0]["id"]
    assert (
        client.get(
            f"/api/v1/workspaces/{team.ws}/audit-logs?limit=1001", headers=team.h("owner")
        ).status_code
        == 422
    )


def test_market_node_registered_per_workspace(client: TestClient, team: Team) -> None:
    def types() -> set[str]:
        return {
            n["type"]
            for n in client.get(
                f"/api/v1/workspaces/{team.ws}/nodes", headers=team.h("builder")
            ).json()
        }

    assert "text_tools" not in types()
    install(client, team, "node_text_tools")
    assert "text_tools" in types()
    assert registry.get("text_tools") is not None
    graph = {
        "version": 1,
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "t"}]}},
            {
                "id": "n2",
                "type": "text_tools",
                "data": {"text": "  안녕   하세요 ", "operation": "trim"},
            },
            {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}/{{n2.length}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
        "variables": {},
    }
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "단계"}, headers=team.h("builder")
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {}}, headers=team.h("builder")
    ).json()
    assert run["output"]["text"] == "안녕 하세요/6"
    # 제거하면 이 워크스페이스에서 다시 못 쓴다
    inst = client.get(
        f"/api/v1/workspaces/{team.ws}/market/installations", headers=team.h("member")
    ).json()
    node_inst = next(i for i in inst if i["item_key"] == "node_text_tools")
    assert (
        client.delete(
            f"/api/v1/workspaces/{team.ws}/market/installations/{node_inst['id']}",
            headers=team.h("admin"),
        ).status_code
        == 204
    )
    assert "text_tools" not in types()
    res = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert not res["valid"]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("import os\n", "'os' 모듈은 쓸 수 없어요"),
        ("from subprocess import run\n", "'subprocess' 모듈은 쓸 수 없어요"),
        ("x = eval('1')\n", "'eval'는 쓸 수 없어요"),
        ("x = ().__class__\n", "밑줄 두 개"),
    ],
)
def test_bundle_validation_rejects_unsafe_code(tmp_path: Path, code: str, message: str) -> None:
    manifest = {"key": "bad", "type": "node", "name": "bad", "version": "1.0.0", "permissions": []}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "node.py").write_text(code, encoding="utf-8")
    with pytest.raises(BundleError) as exc:
        validate_bundle(tmp_path, manifest)
    assert message in str(exc.value)


def test_connector_requires_declared_domain(tmp_path: Path) -> None:
    manifest = {
        "key": "c",
        "type": "connector",
        "name": "c",
        "version": "1",
        "actions": [{"key": "a"}],
        "permissions": [],
    }
    (tmp_path / "connector.py").write_text("def a(p, s, n):\n    return {}\n", encoding="utf-8")
    with pytest.raises(BundleError) as exc:
        validate_bundle(tmp_path, manifest)
    assert "도메인" in str(exc.value)


def test_credentials_masked_and_validated(client: TestClient, team: Team) -> None:
    install(client, team, "email")
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "email", "name": "메일", "secrets": {"host": "smtp.example.com"}},
        headers=team.h("admin"),
    )
    assert res.status_code == 422 and "빠진 값" in res.json()["detail"]["message"]
    secrets = {
        "host": "smtp.example.com",
        "port": "587",
        "username": "u",
        "password": "super-secret-pw",
        "sender": "a@b.co",
    }
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "email", "name": "메일", "secrets": secrets},
        headers=team.h("admin"),
    )
    assert res.status_code == 200
    listed = client.get(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials", headers=team.h("builder")
    ).text
    assert "super-secret-pw" not in listed and "****t-pw" in listed


def test_template_app_uses_installed_template(client: TestClient, team: Team) -> None:
    install(client, team, "tpl_doc_summary")
    tpls = client.get(f"/api/v1/workspaces/{team.ws}/templates", headers=team.h("builder")).json()
    assert [t["key"] for t in tpls] == ["tpl_doc_summary"]
    app = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "요약", "template_key": "tpl_doc_summary"},
        headers=team.h("builder"),
    ).json()
    assert [n["type"] for n in app["draft_graph"]["nodes"]] == ["input", "llm", "output"]
    v = client.post(f"/api/v1/apps/{app['id']}/versions", json={}, headers=team.h("builder"))
    assert v.status_code == 201 and v.json()["version"] == 1


# ---------------- 배포·공개 ----------------
def _published_app(
    client: TestClient, team: Team, access: str, roles: list[str] | None = None
) -> str:
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "공개"}, headers=team.h("builder")
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/apps/{app_id}/deployments",
            json={"channel": "share_link"},
            headers=team.h("builder"),
        ).status_code
        == 422
    )
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    body: dict[str, Any] = {"channel": "share_link", "access": access}
    if roles is not None:
        body["allowed_roles"] = roles
    res = client.post(f"/api/v1/apps/{app_id}/deployments", json=body, headers=team.h("builder"))
    assert res.status_code == 201, res.text
    token: str = res.json()["public_token"]
    return token


def _chat(client: TestClient, token: str, headers: dict[str, str] | None = None) -> Any:
    return client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "안녕"}, headers=headers or {}
    )


def test_public_access_rules(client: TestClient, team: Team, outsider: dict[str, str]) -> None:
    public = _published_app(client, team, "public")
    res = _chat(client, public)
    assert res.status_code == 200 and "event: answer" in res.text and "안녕" in res.text

    ws_only = _published_app(client, team, "workspace")
    assert _chat(client, ws_only).status_code == 401
    assert _chat(client, ws_only, outsider).status_code == 403
    assert _chat(client, ws_only, team.h("member")).status_code == 200
    info = client.get(f"/api/v1/public/apps/{ws_only}").json()
    assert info["requires_login"] and not info["can_use"]

    roles = _published_app(client, team, "roles", ["member"])
    assert _chat(client, roles, team.h("member")).status_code == 200
    assert _chat(client, roles, team.h("operator")).status_code == 403
    assert _chat(client, roles, team.h("owner")).status_code == 200


def test_public_rate_limit(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _published_app(client, team, "public")
    ratelimit.reset()
    monkeypatch.setattr(
        ratelimit,
        "get_settings",
        lambda: type("S", (), {"genio_public_rate_limit_per_minute": 3})(),
    )
    codes = [_chat(client, token).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_widget_js_and_conversation(client: TestClient, team: Team) -> None:
    token = _published_app(client, team, "public")
    js = client.get(f"/api/v1/public/apps/{token}/widget.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert f"/share/{token}?embed=1" in js.text
    first = client.post(f"/api/v1/public/apps/{token}/chat", json={"message": "첫 질문"}).text
    session = json.loads(first.split("event: session\ndata: ", 1)[1].split("\n", 1)[0])[
        "session_id"
    ]
    second = client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "두 번째", "session_id": session}
    ).text
    assert session in second
    assert client.get("/api/v1/public/apps/nope/widget.js").status_code == 404


def test_undeploy_returns_to_draft(client: TestClient, team: Team) -> None:
    token = _published_app(client, team, "public")
    app = client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=team.h("builder")).json()[0]
    assert app["status"] == "published"
    deps = client.get(f"/api/v1/apps/{app['id']}/deployments", headers=team.h("operator")).json()
    assert deps[0]["public_token"] == token and "<script" in deps[0]["widget_snippet"]
    assert (
        client.delete(f"/api/v1/deployments/{deps[0]['id']}", headers=team.h("builder")).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/apps/{app['id']}", headers=team.h("builder")).json()["status"]
        == "draft"
    )
    assert _chat(client, token).status_code == 404


# ---------------- 지식베이스 ----------------
def test_chunking_keeps_paragraphs() -> None:
    text = "가" * 50 + "\n\n" + "나" * 50 + "\n\n" + "다" * 900
    chunks = chunk_text(text, size=200, overlap=20)
    assert chunks[0].startswith("가") and "나" in chunks[0]
    assert all(len(c) <= 200 for c in chunks)
    assert len(chunks) >= 5


def test_kb_upload_search_and_failure(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "규정"},
        headers=team.h("builder"),
    ).json()
    # 임베딩 연결이 없으면 실패 사유를 문서에 남긴다
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("a.txt", "재택근무는 주 2회".encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    assert doc["status"] == "failed" and "AI 연결" in doc["error"]
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    for name, body in [
        ("leave.txt", "연차는 15일이고 3년마다 늘어난다."),
        ("remote.md", "재택근무는 주 2회까지 가능하다."),
    ]:
        d = client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            files={"file": (name, body.encode(), "text/plain")},
            headers=team.h("builder"),
        ).json()
        assert d["status"] == "ready" and d["chunk_count"] == 1
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/search",
        json={"query": "재택근무 며칠", "top_k": 1},
        headers=team.h("builder"),
    ).json()
    assert hits[0]["filename"] == "remote.md"
    bad = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
        headers=team.h("builder"),
    )
    assert bad.status_code == 415
    docs = client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=team.h("operator")
    ).json()
    assert len(docs) == 3


# ---------------- 인증 ----------------
def test_signup_login_refresh_me(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "New@Example.com",
            "password": "Spring2026walk",
            "name": "새 사람",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    assert res.status_code == 200
    tokens = res.json()
    me = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()
    assert me["email"] == "new@example.com" and me["workspaces"][0]["role"] == "owner"
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={
                "email": "new@example.com",
                "password": "Spring2026walk",
                "name": "x",
                "agree_terms": True,
                "agree_privacy": True,
            },
        ).status_code
        == 409
    )
    bad = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": "wrong-pass"}
    )
    assert bad.status_code == 401 and bad.json()["detail"]["hint"]
    ok = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": "Spring2026walk"}
    )
    assert ok.status_code == 200
    ref = client.post("/api/v1/auth/refresh", json={"refresh_token": ok.json()["refresh_token"]})
    assert ref.status_code == 200
    # access 토큰으로 refresh 할 수 없다
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        ).status_code
        == 401
    )


def test_short_password_rejected_in_korean(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "a@b.co",
            "password": "123",
            "name": "x",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"]["message"] == "입력값이 올바르지 않아요: 비밀번호"


def test_invitation_flow(client: TestClient, team: Team) -> None:
    inv = client.post(
        f"/api/v1/workspaces/{team.ws}/invitations",
        json={"email": "guest@example.com", "role": "operator"},
        headers=team.h("admin"),
    ).json()
    assert inv["accept_url"].endswith(f"/invite/{inv['token']}")
    info = client.get(f"/api/v1/auth/invitations/{inv['token']}").json()
    assert info["role"] == "operator" and not info["expired"]
    tokens = client.post(
        f"/api/v1/auth/invitations/{inv['token']}/accept",
        json={"name": "손님", "password": "guestpass1", "agree_terms": True, "agree_privacy": True},
    ).json()
    me = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()
    assert me["workspaces"][0]["role"] == "operator"
    again = client.post(
        f"/api/v1/auth/invitations/{inv['token']}/accept",
        json={"name": "손님", "password": "guestpass1", "agree_terms": True, "agree_privacy": True},
    )
    assert again.status_code == 409


def test_graph_schema_endpoint(client: TestClient) -> None:
    schema = client.get("/api/v1/schemas/graph").json()
    assert schema["title"] == "Graph"
    assert "sourceHandle" in schema["$defs"]["GraphEdge"]["properties"]


def test_delete_app_with_runs_deployments_and_chats(client: TestClient, team: Team) -> None:
    """앱을 지우면 버전·배포·실행·대화가 함께 정리된다(외래 키 삭제 규칙 회귀 테스트)."""
    token = _published_app(client, team, "public")
    assert _chat(client, token).status_code == 200
    app = client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=team.h("builder")).json()[0]
    res = client.delete(f"/api/v1/apps/{app['id']}", headers=team.h("builder"))
    assert res.status_code == 204, res.text
    assert client.get(f"/api/v1/public/apps/{token}").status_code == 404
    assert client.get(f"/api/v1/workspaces/{team.ws}/runs", headers=team.h("owner")).json() == []


def test_login_trims_email_and_hints_ime(client: TestClient, team: Team) -> None:
    ok = client.post(
        "/api/v1/auth/login", json={"email": "  Owner@Test.local ", "password": "password123!"}
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/v1/auth/login", json={"email": "owner@test.local", "password": "ㅔㅁㄴㄴ재같123!"}
    )
    assert bad.status_code == 401 and "한/영" in bad.json()["detail"]["hint"]


def test_demo_accounts_not_public(client: TestClient) -> None:
    """로그인 화면에 역할별 데모 계정·비밀번호를 공개하지 않는다(관리 콘솔에서 계정 관리)."""
    assert client.get("/api/v1/auth/demo-accounts").status_code in (404, 405)


def test_old_password_hash_upgraded_on_login(client: TestClient, team: Team) -> None:
    import bcrypt

    from api.core.security import BCRYPT_ROUNDS
    from api.db import SessionLocal
    from api.models import User

    with SessionLocal() as db:
        u = db.get(User, team.users["admin"])
        assert u is not None
        u.password_hash = bcrypt.hashpw(b"password123!", bcrypt.gensalt(12)).decode()
        db.commit()
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "admin@test.local", "password": "password123!"}
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        u = db.get(User, team.users["admin"])
        assert u is not None and u.password_hash.startswith(f"$2b${BCRYPT_ROUNDS}$")
