"""v0.2 앱 기능·로그·주석·모니터링·API 키·서비스 API·내보내기·지식베이스 확장·관리 콘솔."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.tests.conftest import ROLES, Team, add_llm, membership_id
from api.tests.fakes import FakeAdapter

KB_DOC = "연차는 15일이다.\n\n재택근무는 주 2회까지 가능하다.\n\n경조 휴가는 5일이다."


def parse_sse(body: str) -> list[tuple[str, Any]]:
    out = []
    for frame in body.split("\n\n"):
        name, data = None, None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            out.append((name, data))
    return out


def faq_app(client: TestClient, team: Team, *, kb_id: str | None = None) -> str:
    nodes: list[dict[str, Any]] = [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "required": True}]}}
    ]
    edges: list[dict[str, Any]] = []
    if kb_id:
        nodes.append(
            {
                "id": "n2",
                "type": "knowledge_search",
                "data": {"kb_id": kb_id, "query": "{{n1.message}}", "top_k": 1},
            }
        )
        nodes.append({"id": "n3", "type": "output", "data": {"template": "답: {{n2.results}}"}})
        edges = [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ]
    else:
        nodes.append({"id": "n3", "type": "output", "data": {"template": "메아리: {{n1.message}}"}})
        edges = [{"id": "e1", "source": "n1", "target": "n3"}]
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "FAQ", "type": "chat"},
        headers=team.h("builder"),
    ).json()["id"]
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": {"version": 1, "nodes": nodes, "edges": edges, "variables": {}}},
        headers=team.h("builder"),
    )
    assert (
        client.post(
            f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder")
        ).status_code
        == 201
    )
    return app_id


def deploy(client: TestClient, team: Team, app_id: str) -> str:
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "public"},
        headers=team.h("builder"),
    )
    token: str = res.json()["public_token"]
    return token


def chat(client: TestClient, token: str, message: str, **extra: Any) -> list[tuple[str, Any]]:
    res = client.post(f"/api/v1/public/apps/{token}/chat", json={"message": message, **extra})
    assert res.status_code == 200, res.text
    return parse_sse(res.text)


# ---------------- 앱 기능 ----------------
def test_features_moderation_annotation_followup_feedback(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id = faq_app(client, team)
    detail = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={
            "opening_statement": "무엇이든 물어보세요",
            "suggested_questions": ["연차는?", " ", "재택은?"],
            "follow_up": {"enabled": True},
            "moderation": {
                "enabled": True,
                "keywords": ["비속어"],
                "preset_reply": "정중하게 말해 주세요",
                "check_output": True,
            },
            "annotation_reply": {"enabled": True, "score_threshold": 0.8},
            "memory": {"window": 99},
            "unknown": 1,
        },
        headers=team.h("builder"),
    ).json()
    f = detail["features"]
    assert (
        f["suggested_questions"] == ["연차는?", "재택은?"]
        and f["memory"]["window"] == 20
        and "unknown" not in f
    )
    token = deploy(client, team, app_id)
    pub = client.get(f"/api/v1/public/apps/{token}").json()
    assert pub["features"]["opening_statement"] == "무엇이든 물어보세요"

    ev = chat(client, token, "이건 비속어 포함")
    assert (
        "moderated",
        {"text": "정중하게 말해 주세요", "message_id": ev[1][1]["message_id"]},
    ) in ev

    ann = client.post(
        f"/api/v1/apps/{app_id}/annotations",
        json={"question": "연차는 며칠이에요?", "answer": "15일이에요."},
        headers=team.h("builder"),
    ).json()
    ev = chat(client, token, "연차는 며칠 이에요")
    annotated = next(d for n, d in ev if n == "annotated")
    assert annotated["text"] == "15일이에요."
    assert (
        client.get(f"/api/v1/apps/{app_id}/annotations", headers=team.h("builder")).json()[0][
            "hit_count"
        ]
        == 1
    )

    ev = chat(client, token, "안녕하세요")
    answer = next(d for n, d in ev if n == "answer")
    assert answer["text"] == "메아리: 안녕하세요"
    assert next(d for n, d in ev if n == "suggestions")  # 이어서 물을 질문
    fb = client.post(
        f"/api/v1/public/apps/{token}/messages/{answer['message_id']}/feedback",
        json={"rating": "like"},
    )
    assert fb.json() == {"ok": True}

    # 로그
    convs = client.get(f"/api/v1/apps/{app_id}/conversations", headers=team.h("operator")).json()
    assert len(convs) == 3 and sum(c["likes"] for c in convs) == 1
    msgs = client.get(
        f"/api/v1/conversations/{convs[0]['id']}/messages", headers=team.h("operator")
    ).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert (
        client.get(
            f"/api/v1/conversations/{convs[0]['id']}/messages", headers=team.h("member")
        ).status_code
        == 403
    )

    # 주석 수정·삭제
    assert (
        client.patch(
            f"/api/v1/annotations/{ann['id']}",
            json={"answer": "15일입니다."},
            headers=team.h("builder"),
        ).json()["answer"]
        == "15일입니다."
    )
    assert (
        client.delete(f"/api/v1/annotations/{ann['id']}", headers=team.h("operator")).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/annotations/{ann['id']}", headers=team.h("builder")).status_code
        == 204
    )

    # 모니터링
    stats = client.get(f"/api/v1/apps/{app_id}/stats?days=7", headers=team.h("operator")).json()
    assert len(stats["days"]) == 7
    t = stats["totals"]
    assert t["conversations"] == 3 and t["likes"] == 1 and t["runs"] == 1 and t["messages"] == 6


def test_conversation_memory_and_variables(client: TestClient, team: Team) -> None:
    graph = {
        "version": 1,
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {
                "id": "n2",
                "type": "variable_assigner",
                "data": {
                    "assignments": [
                        {"variable": "count", "value": "{{ (conv.count or 0) | int + 1 }}"}
                    ]
                },
            },
            {
                "id": "n3",
                "type": "output",
                "data": {"template": "{{conv.count}}번째 | 기록: {{input.history}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
        "variables": {},
    }
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "기억", "type": "chat"},
        headers=team.h("builder"),
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    token = deploy(client, team, app_id)
    ev1 = chat(client, token, "하나")
    sid = next(d for n, d in ev1 if n == "session")["session_id"]
    ev2 = chat(client, token, "둘", session_id=sid)
    text = next(d for n, d in ev2 if n == "answer")["text"]
    assert text.startswith("2번째") and "user: 하나" in text and "assistant: 1번째" in text


def test_chat_file_upload_feature(client: TestClient, team: Team) -> None:
    graph = {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {"fields": [{"key": "message"}, {"key": "doc", "type": "file"}]},
            },
            {"id": "n2", "type": "document_extractor", "data": {"file": "{{n1.doc}}"}},
            {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
        "variables": {},
    }
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "파일", "type": "chat"},
        headers=team.h("builder"),
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    token = deploy(client, team, app_id)
    files = {"file": ("a.txt", "첨부 내용".encode(), "text/plain")}
    assert client.post(f"/api/v1/public/apps/{token}/files", files=files).status_code == 403
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"file_upload": {"enabled": True}},
        headers=team.h("builder"),
    )
    fid = client.post(f"/api/v1/public/apps/{token}/files", files=files).json()["id"]
    ev = chat(client, token, "요약", files=[fid])
    assert next(d for n, d in ev if n == "answer")["text"] == "첨부 내용"


# ---------------- API 키·서비스 API ----------------
def test_api_keys_and_service_api(client: TestClient, team: Team) -> None:
    app_id = faq_app(client, team)
    assert (
        client.post(
            f"/api/v1/apps/{app_id}/api-keys", json={"name": "외부"}, headers=team.h("operator")
        ).status_code
        == 403
    )
    created = client.post(
        f"/api/v1/apps/{app_id}/api-keys", json={"name": "외부"}, headers=team.h("builder")
    ).json()
    key = created["key"]
    assert key.startswith("gk-") and created["prefix"].startswith("gk-")
    listed = client.get(f"/api/v1/apps/{app_id}/api-keys", headers=team.h("builder")).text
    assert key not in listed
    h = {"Authorization": f"Bearer {key}"}
    params = client.get("/api/v1/service/parameters", headers=h).json()
    assert params["input_fields"][0]["key"] == "message"
    r1 = client.post("/api/v1/service/chat-messages", json={"query": "안녕"}, headers=h).json()
    assert r1["answer"] == "메아리: 안녕" and r1["conversation_id"]
    r2 = client.post(
        "/api/v1/service/chat-messages",
        json={"query": "또", "conversation_id": r1["conversation_id"]},
        headers=h,
    ).json()
    assert r2["conversation_id"] == r1["conversation_id"]
    wf = client.post(
        "/api/v1/service/workflows/run", json={"inputs": {"message": "실행"}}, headers=h
    ).json()
    assert wf["status"] == "succeeded" and wf["outputs"]["text"] == "메아리: 실행"
    assert (
        client.get(
            "/api/v1/service/parameters", headers={"Authorization": "Bearer gk-wrong"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/service/parameters").status_code == 401
    admin_keys = client.get(
        f"/api/v1/workspaces/{team.ws}/admin/api-keys", headers=team.h("admin")
    ).json()
    assert admin_keys[0]["app_name"] == "FAQ" and admin_keys[0]["last_used_at"]
    assert (
        client.delete(f"/api/v1/api-keys/{created['id']}", headers=team.h("builder")).status_code
        == 204
    )
    assert client.get("/api/v1/service/parameters", headers=h).status_code == 401


# ---------------- 내보내기·가져오기·복제·되돌리기 ----------------
def test_export_import_duplicate_restore(client: TestClient, team: Team) -> None:
    app_id = faq_app(client, team)
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"opening_statement": "안녕"},
        headers=team.h("builder"),
    )
    data = client.get(f"/api/v1/apps/{app_id}/export", headers=team.h("builder")).json()
    assert data["genio_version"] == "0.2" and data["app"]["features"]["opening_statement"] == "안녕"
    imported = client.post(
        f"/api/v1/workspaces/{team.ws}/apps/import", json=data, headers=team.h("builder")
    )
    assert (
        imported.status_code == 201 and imported.json()["features"]["opening_statement"] == "안녕"
    )
    bad = client.post(
        f"/api/v1/workspaces/{team.ws}/apps/import",
        json={**data, "graph": {"nodes": "x"}},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422
    dup = client.post(f"/api/v1/apps/{app_id}/duplicate", headers=team.h("builder")).json()
    assert dup["name"] == "FAQ (복사본)" and dup["latest_version"] is None
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": {"version": 1, "nodes": [], "edges": [], "variables": {}}},
        headers=team.h("builder"),
    )
    restored = client.post(
        f"/api/v1/apps/{app_id}/versions/1/restore", headers=team.h("builder")
    ).json()
    assert len(restored["draft_graph"]["nodes"]) == 2


# ---------------- 지식베이스 ----------------
def test_kb_settings_parent_child_methods_metadata_chunks(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "규정"},
        headers=team.h("builder"),
    ).json()
    assert kb["settings"]["retrieval"]["method"] == "vector"
    upd = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={
            "settings": {
                "chunk_mode": "parent_child",
                "child_chunk_size": 50,
                "retrieval": {"method": "hybrid", "top_k": 99, "vector_weight": 0.5},
            }
        },
        headers=team.h("builder"),
    ).json()
    assert (
        upd["settings"]["retrieval"]["top_k"] == 20
        and upd["settings"]["chunk_mode"] == "parent_child"
    )
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("규정.txt", KB_DOC.encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    assert doc["status"] == "ready"
    chunks = client.get(f"/api/v1/documents/{doc['id']}/chunks", headers=team.h("operator")).json()
    assert len(chunks) == 3 and all(c["parent_content"] for c in chunks)

    for method in ("vector", "keyword", "hybrid"):
        hits = client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/search",
            json={"query": "재택근무 며칠", "method": method, "top_k": 1},
            headers=team.h("builder"),
        ).json()
        assert "재택근무" in hits[0]["matched"], method
        assert "연차" in hits[0]["content"]  # 부모 문단을 돌려준다

    # 조각 끄기 → 검색에서 빠짐, 내용 고치기 → 다시 임베딩
    target = next(c for c in chunks if "재택" in c["content"])
    client.patch(
        f"/api/v1/chunks/{target['id']}", json={"enabled": False}, headers=team.h("builder")
    )
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/search",
        json={"query": "재택근무", "method": "keyword"},
        headers=team.h("builder"),
    ).json()
    assert all("재택" not in h["matched"] for h in hits)
    edited = client.patch(
        f"/api/v1/chunks/{target['id']}",
        json={"content": "재택근무는 주 3회", "enabled": True},
        headers=team.h("builder"),
    ).json()
    assert edited["content"] == "재택근무는 주 3회"

    # 메타데이터 필터
    doc2 = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("인사.txt", "재택근무 신청은 인사팀에 한다.".encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    client.patch(
        f"/api/v1/documents/{doc2['id']}",
        json={"metadata": {"dept": "인사"}},
        headers=team.h("builder"),
    )
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/search",
        json={"query": "재택근무", "metadata_filter": {"dept": "인사"}},
        headers=team.h("builder"),
    ).json()
    assert {h["filename"] for h in hits} == {"인사.txt"} and hits[0]["metadata"] == {"dept": "인사"}

    # 웹 페이지 가져오기
    monkeypatch.setattr(
        safe_http,
        "request",
        lambda m, u, **kw: {
            "status": 200,
            "body": "<html><head><title>복지 안내</title></head><body><p>식대는 월 20만 원 지원한다.</p><p>통신비는 월 5만 원.</p></body></html>",
            "headers": {},
        },
    )
    web = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/url",
        json={"url": "https://intranet.example.com/welfare"},
        headers=team.h("builder"),
    ).json()
    assert (
        web["status"] == "ready" and web["source"] == "url" and web["filename"] == "복지 안내.txt"
    )
    assert (
        client.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=team.h("builder")).json()[
            "status"
        ]
        == "ready"
    )


# ---------------- 관리 콘솔 ----------------
def test_admin_console(client: TestClient, team: Team) -> None:
    faq_app(client, team)
    ov = client.get(
        f"/api/v1/workspaces/{team.ws}/admin/overview?days=7", headers=team.h("admin")
    ).json()
    assert ov["counts"]["members"] == 5 and ov["counts"]["apps"] == 1 and len(ov["days"]) == 7
    for role in ("builder", "operator", "member"):
        assert (
            client.get(
                f"/api/v1/workspaces/{team.ws}/admin/overview", headers=team.h(role)
            ).status_code
            == 403
        )

    # 워크스페이스 설정·기본 모델
    prov = add_llm(client, team, provider="openai", model="gpt-4o-mini")
    ws = client.patch(
        f"/api/v1/workspaces/{team.ws}",
        json={
            "name": "새 이름",
            "settings": {
                "default_models": {"chat": prov["id"], "embedding": "없는id"},
                "public_rate_limit_per_minute": 5,
            },
        },
        headers=team.h("admin"),
    ).json()
    assert ws["name"] == "새 이름" and ws["settings"]["default_models"] == {"chat": prov["id"]}
    assert (
        client.get(f"/api/v1/workspaces/{team.ws}", headers=team.h("member")).json()["name"]
        == "새 이름"
    )

    # 멤버 내보내기·초대 취소·소유권 넘기기
    assert (
        client.delete(
            f"/api/v1/workspaces/{team.ws}/members/{membership_id(team, 'owner')}",
            headers=team.h("admin"),
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{team.ws}/members/{membership_id(team, 'admin')}",
            headers=team.h("admin"),
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/workspaces/{team.ws}/members/{membership_id(team, 'member')}",
            headers=team.h("admin"),
        ).status_code
        == 204
    )
    inv = client.post(
        f"/api/v1/workspaces/{team.ws}/invitations",
        json={"email": "x@example.com", "role": "member"},
        headers=team.h("admin"),
    ).json()
    assert (
        client.delete(
            f"/api/v1/workspaces/{team.ws}/invitations/{inv['id']}", headers=team.h("admin")
        ).status_code
        == 204
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/transfer-ownership",
            json={"member_id": membership_id(team, "builder")},
            headers=team.h("admin"),
        ).status_code
        == 403
    )
    assert client.post(
        f"/api/v1/workspaces/{team.ws}/transfer-ownership",
        json={"member_id": membership_id(team, "builder")},
        headers=team.h("owner"),
    ).json() == {"ok": True}
    roles = {
        m["email"].split("@")[0]: m["role"]
        for m in client.get(
            f"/api/v1/workspaces/{team.ws}/members", headers=team.h("builder")
        ).json()
    }
    assert roles["builder"] == "owner" and roles["owner"] == "admin"

    # 시스템 설정: 인스턴스 관리자(첫 워크스페이스 owner = 지금은 builder)만
    assert (
        client.get("/api/v1/admin/system", headers=team.h("builder")).json()["is_instance_admin"]
        is True
    )
    assert (
        client.patch(
            "/api/v1/admin/system", json={"allow_signup": False}, headers=team.h("owner")
        ).status_code
        == 403
    )
    sysset = client.patch(
        "/api/v1/admin/system",
        json={"allow_signup": False},
        headers=team.h("builder"),
    ).json()
    assert sysset["allow_signup"] is False
    assert (
        client.post(
            "/api/v1/auth/signup",
            json={"email": "n@example.com", "password": "abcd1234", "name": "n"},
        ).status_code
        == 403
    )
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("admin")).json()
    actions = {entry["action"] for entry in logs}
    assert {
        "member.remove",
        "member.invite_revoke",
        "workspace.transfer_ownership",
        "workspace.update",
        "system.update",
    } <= actions


@pytest.mark.parametrize("role", ROLES)
def test_v02_permissions(client: TestClient, team: Team, role: str) -> None:
    app_id = faq_app(client, team)
    edit = role in ("owner", "admin", "builder")
    view = role != "member"
    codes = {
        "features": client.patch(
            f"/api/v1/apps/{app_id}/features", json={}, headers=team.h(role)
        ).status_code,
        "env": client.put(
            f"/api/v1/apps/{app_id}/env-vars", json={"env_vars": []}, headers=team.h(role)
        ).status_code,
        "export": client.get(f"/api/v1/apps/{app_id}/export", headers=team.h(role)).status_code,
        "annotations": client.get(
            f"/api/v1/apps/{app_id}/annotations", headers=team.h(role)
        ).status_code,
        "keys": client.get(f"/api/v1/apps/{app_id}/api-keys", headers=team.h(role)).status_code,
        "logs": client.get(
            f"/api/v1/apps/{app_id}/conversations", headers=team.h(role)
        ).status_code,
        "stats": client.get(f"/api/v1/apps/{app_id}/stats", headers=team.h(role)).status_code,
    }
    for k in ("features", "env", "export", "annotations", "keys"):
        assert (codes[k] < 400) == edit, (k, role, codes[k])
    for k in ("logs", "stats"):
        assert (codes[k] < 400) == view, (k, role, codes[k])
