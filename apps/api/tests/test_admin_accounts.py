"""관리 콘솔 계정 관리: 계정 만들기, 비밀번호 재설정, 역할별 권한."""

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import AuditLog, Membership, Workspace
from api.tests.conftest import Team


def _login(client: TestClient, email: str, password: str) -> int:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    ).status_code


def test_create_account(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/admin/accounts"
    out = client.post(
        url,
        json={"email": " Hong@Corp.Local ", "name": "홍길동", "role": "builder"},
        headers=team.h("admin"),
    )
    assert out.status_code == 201
    d = out.json()
    pw = d["temporary_password"]
    assert len(pw) == 12 and d["member"]["role"] == "builder" and d["member"]["only_here"]
    assert d["member"]["email"] == "hong@corp.local"
    assert _login(client, "hong@corp.local", pw) == 200
    # 새 계정은 이 워크스페이스에만 들어간다
    me = client.get(
        "/api/v1/me",
        headers={
            "Authorization": "Bearer "
            + client.post(
                "/api/v1/auth/login", json={"email": "hong@corp.local", "password": pw}
            ).json()["access_token"]
        },
    ).json()
    assert [w["id"] for w in me["workspaces"]] == [team.ws]
    assert me["preferences"]["default_workspace_id"] == team.ws

    # 직접 정한 비밀번호는 다시 돌려주지 않는다
    own = client.post(
        url,
        json={"email": "kim@corp.local", "name": "김", "password": "mypass1234"},
        headers=team.h("owner"),
    ).json()
    assert own["temporary_password"] is None and own["member"]["role"] == "member"
    assert _login(client, "kim@corp.local", "mypass1234") == 200

    # 중복 이메일, 잘못된 형식, 권한
    dup = client.post(url, json={"email": "hong@corp.local", "name": "x"}, headers=team.h("owner"))
    assert dup.status_code == 409 and "초대" in dup.json()["detail"]["hint"]
    assert (
        client.post(url, json={"email": "nope", "name": "x"}, headers=team.h("owner")).status_code
        == 422
    )
    assert (
        client.post(
            url, json={"email": "a@b.co", "name": "x", "role": "owner"}, headers=team.h("admin")
        ).status_code
        == 403
    )
    for role in ("builder", "operator", "member"):
        assert (
            client.post(
                url, json={"email": "z@b.co", "name": "x"}, headers=team.h(role)
            ).status_code
            == 403
        )
    # 비밀번호는 활동 기록에 남지 않는다
    with SessionLocal() as db:
        logs = [a for a in db.query(AuditLog).all() if a.action == "member.account_create"]
        assert len(logs) == 2 and all(pw not in str(a.meta) for a in logs)


def test_reset_password(client: TestClient, team: Team) -> None:
    members = client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("admin")).json()
    by_role = {m["role"]: m for m in members}
    base = f"/api/v1/workspaces/{team.ws}/members"

    out = client.post(f"{base}/{by_role['member']['id']}/reset-password", headers=team.h("admin"))
    assert out.status_code == 200
    pw = out.json()["temporary_password"]
    assert _login(client, by_role["member"]["email"], pw) == 200

    # 자기 자신, 관리자·소유자 계정(관리자가 시도), 낮은 역할은 거부
    assert (
        client.post(
            f"{base}/{by_role['admin']['id']}/reset-password", headers=team.h("admin")
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{base}/{by_role['owner']['id']}/reset-password", headers=team.h("admin")
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/{by_role['admin']['id']}/reset-password", headers=team.h("owner")
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{base}/{by_role['member']['id']}/reset-password", headers=team.h("builder")
        ).status_code
        == 403
    )

    # 다른 워크스페이스에도 속한 계정은 재설정 불가
    with SessionLocal() as db:
        other = Workspace(org_id=db.get(Workspace, team.ws).org_id, name="다른 곳", slug="other-ws")  # type: ignore[union-attr]
        db.add(other)
        db.flush()
        db.add(Membership(user_id=team.users["operator"], workspace_id=other.id, role="member"))
        db.commit()
    members = client.get(base, headers=team.h("owner")).json()
    op = next(m for m in members if m["role"] == "operator")
    assert op["only_here"] is False
    shared = client.post(f"{base}/{op['id']}/reset-password", headers=team.h("owner"))
    assert shared.status_code == 409 and "내 설정" in shared.json()["detail"]["hint"]
