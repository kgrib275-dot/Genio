"""v0.8 공유 링크 미리보기: 제목·소개 문구·썸네일(Open Graph), 비공개 앱 보호, 이스케이프."""

import io
import struct
import zlib
from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team
from api.tests.test_v05_engine import make_app

GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {"id": "n2", "type": "output", "data": {"template": "{{n1.message}}"}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}


def _png(w: int = 4, h: int = 4) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _deploy(
    client: TestClient, team: Team, access: str = "public", **app_fields: Any
) -> tuple[str, str, str]:
    h = team.h("builder")
    app_id = make_app(client, team, GRAPH, name=app_fields.get("name", "휴가 신청 도우미"))
    if app_fields.get("description"):
        client.patch(
            f"/api/v1/apps/{app_id}", json={"description": app_fields["description"]}, headers=h
        )
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h)
    d = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={
            "channel": "share_link",
            "access": access,
            **({"allowed_roles": ["member"]} if access == "roles" else {}),
        },
        headers=h,
    ).json()
    return app_id, d["id"], d["public_token"]


def _upload(client: TestClient, team: Team, name: str, data: bytes, mime: str) -> str:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": (name, io.BytesIO(data), mime)},
        headers=team.h("builder"),
    )
    assert r.status_code in (200, 201), r.text
    return str(r.json()["id"])


def test_default_preview_for_unknown_and_generic(client: TestClient) -> None:
    for token in ("-", "nope-nope"):
        r = client.get(f"/api/v1/public/share/{token}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
        assert 'property="og:title" content="제니오 — 말로 만드는 나만의 앱"' in r.text
        assert 'property="og:image" content="http' in r.text
        assert "og-default.png" in r.text
    img = client.get("/api/v1/public/og-default.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_public_app_uses_name_and_description(client: TestClient, team: Team) -> None:
    _, _, token = _deploy(
        client, team, name="휴가 신청 도우미", description="사내 휴가를 물어보고 신청해요"
    )
    r = client.get(f"/api/v1/public/share/{token}")
    assert 'og:title" content="휴가 신청 도우미"' in r.text
    assert 'og:description" content="사내 휴가를 물어보고 신청해요"' in r.text
    assert f"/api/v1/public/apps/{token}/share-image" in r.text and f"/share/{token}" in r.text
    j = client.get(f"/api/v1/public/share-meta/{token}").json()
    assert j["title"] == "휴가 신청 도우미" and j["description"].startswith("사내 휴가")


def test_custom_title_description_and_thumbnail(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team)
    file_id = _upload(client, team, "thumb.png", _png(), "image/png")
    r = client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={
            "appearance": {
                "share_title": "우리 팀 휴가 봇",
                "share_description": "연차·반차를 말로 신청하세요. 승인 결과도 알려 드려요.",
                "share_image": file_id,
            }
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["appearance"]["share_title"] == "우리 팀 휴가 봇"
    page = client.get(f"/api/v1/public/share/{token}").text
    assert 'og:title" content="우리 팀 휴가 봇"' in page and "연차·반차를 말로 신청하세요" in page
    img = client.get(f"/api/v1/public/apps/{token}/share-image")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content == _png() and img.headers["cache-control"].startswith("public")
    # 앱 설정 화면이 쓰는 공개 정보에도 들어 있다
    assert (
        client.get(f"/api/v1/public/apps/{token}").json()["appearance"]["share_title"]
        == "우리 팀 휴가 봇"
    )


def test_bad_thumbnail_rejected_and_other_workspace_file(client: TestClient, team: Team) -> None:
    _, dep_id, _ = _deploy(client, team)
    pdf = _upload(client, team, "x.pdf", b"%PDF-1.4 test", "application/pdf")
    for bad in (pdf, "no-such-file"):
        r = client.patch(
            f"/api/v1/deployments/{dep_id}",
            json={"appearance": {"share_image": bad}},
            headers=team.h("builder"),
        )
        assert r.status_code == 422
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]
    # 너무 긴 제목·소개는 형식 오류
    r = client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"share_title": "가" * 61}},
        headers=team.h("builder"),
    )
    assert r.status_code == 422


def test_members_only_app_is_not_leaked(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team, access="roles", name="급여 조회 비밀 봇")
    client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"share_title": "급여 비밀 제목"}},
        headers=team.h("builder"),
    )
    page = client.get(f"/api/v1/public/share/{token}").text
    assert "급여" not in page and "제니오 — 말로 만드는 나만의 앱" in page
    assert client.get(f"/api/v1/public/share-meta/{token}").json()["title"].startswith("제니오")
    # 그림도 기본 그림만 나간다
    img = client.get(f"/api/v1/public/apps/{token}/share-image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"


def test_html_is_escaped(client: TestClient, team: Team) -> None:
    _, dep_id, token = _deploy(client, team, name="앱")
    client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"share_title": '"><script>alert(1)</script>'}},
        headers=team.h("builder"),
    )
    page = client.get(f"/api/v1/public/share/{token}").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
