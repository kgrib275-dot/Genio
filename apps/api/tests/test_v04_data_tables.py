"""v0.4 데이터 표: 표·줄 권한, 키, 검색, CSV, 프로젝트 공개 범위, 한도(ADR 0008)."""

import pytest
from fastapi.testclient import TestClient

from api.services import data_tables
from api.tests.conftest import ROLES, Team


def make_table(client: TestClient, team: Team, name: str = "고객", **extra: object) -> dict:  # type: ignore[type-arg]
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/data-tables",
        json={
            "name": name,
            "columns": [
                {"key": "name", "label": "이름", "type": "text"},
                {"key": "visits", "label": "방문 수", "type": "number"},
                {"key": "vip", "type": "boolean"},
            ],
            **extra,
        },
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    return res.json()  # type: ignore[no-any-return]


def test_table_permissions(client: TestClient, team: Team) -> None:
    for role in ROLES:
        res = client.post(
            f"/api/v1/workspaces/{team.ws}/data-tables",
            json={"name": f"표-{role}"},
            headers=team.h(role),
        )
        assert res.status_code == (201 if role in ("owner", "admin", "builder") else 403), role
    t = make_table(client, team)
    for role in ROLES:
        assert (
            client.get(
                f"/api/v1/workspaces/{team.ws}/data-tables", headers=team.h(role)
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/v1/data-tables/{t['id']}/rows", headers=team.h(role)).status_code
            == 200
        )
        add = client.post(
            f"/api/v1/data-tables/{t['id']}/rows",
            json={"data": {"name": role}},
            headers=team.h(role),
        )
        assert add.status_code == (403 if role == "member" else 201), role
        patch = client.patch(
            f"/api/v1/data-tables/{t['id']}", json={"description": "x"}, headers=team.h(role)
        )
        assert patch.status_code == (200 if role in ("owner", "admin", "builder") else 403), role
    dup = client.post(
        f"/api/v1/workspaces/{team.ws}/data-tables",
        json={"name": "고객"},
        headers=team.h("builder"),
    )
    assert dup.status_code == 409 and dup.json()["detail"]["hint"]
    bad = client.post(
        f"/api/v1/workspaces/{team.ws}/data-tables",
        json={"name": "잘못", "columns": [{"key": "1bad"}]},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422
    assert (
        client.delete(f"/api/v1/data-tables/{t['id']}", headers=team.h("operator")).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/data-tables/{t['id']}", headers=team.h("builder")).status_code
        == 204
    )


def test_rows_keys_search_types(client: TestClient, team: Team) -> None:
    t = make_table(client, team)
    url = f"/api/v1/data-tables/{t['id']}/rows"
    r1 = client.post(
        url,
        json={"row_key": "c1", "data": {"name": "김민지", "visits": "1,200", "vip": "예"}},
        headers=team.h("operator"),
    )
    assert r1.status_code == 201
    row = r1.json()
    # 열 종류에 맞춰 값을 바꾼다
    assert row["data"] == {"name": "김민지", "visits": 1200, "vip": True}
    dup = client.post(url, json={"row_key": "c1", "data": {}}, headers=team.h("operator"))
    assert dup.status_code == 409
    client.post(url, json={"data": {"name": "이서준", "visits": 3}}, headers=team.h("operator"))
    found = client.get(url + "?q=민지", headers=team.h("member")).json()
    assert found["total"] == 1 and found["rows"][0]["row_key"] == "c1"
    page = client.get(url + "?limit=1&offset=1", headers=team.h("member")).json()
    assert page["total"] == 2 and len(page["rows"]) == 1

    upd = client.patch(
        f"/api/v1/data-rows/{row['id']}",
        json={"data": {"name": "김민지", "visits": 5}},
        headers=team.h("operator"),
    )
    assert upd.status_code == 200 and upd.json()["data"]["visits"] == 5
    assert (
        client.patch(
            f"/api/v1/data-rows/{row['id']}", json={"data": {}}, headers=team.h("member")
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/data-rows/{row['id']}", headers=team.h("operator")).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/data-tables/{t['id']}", headers=team.h("member")).json()["row_count"]
        == 1
    )

    huge = client.post(url, json={"data": {"name": "가" * 40000}}, headers=team.h("operator"))
    assert huge.status_code == 413 and huge.json()["detail"]["hint"]


def test_csv_import_export(client: TestClient, team: Team) -> None:
    t = make_table(client, team)
    csv_body = "row_key,name,visits,city\nc1,김민지,3,서울\nc2,이서준,7,부산\n".encode("utf-8-sig")
    res = client.post(
        f"/api/v1/data-tables/{t['id']}/import",
        files={"file": ("customers.csv", csv_body, "text/csv")},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["imported"] == 2
    assert "city" in [c["key"] for c in res.json()["columns"]]
    # 같은 키로 다시 가져오면 덮어쓴다
    again = b"row_key,visits\nc1,10\n"
    client.post(
        f"/api/v1/data-tables/{t['id']}/import",
        files={"file": ("a.csv", again, "text/csv")},
        headers=team.h("builder"),
    )
    rows = client.get(f"/api/v1/data-tables/{t['id']}/rows", headers=team.h("member")).json()
    assert rows["total"] == 2
    c1 = next(r for r in rows["rows"] if r["row_key"] == "c1")
    assert c1["data"]["visits"] == 10 and c1["data"]["city"] == "서울"
    assert (
        client.post(
            f"/api/v1/data-tables/{t['id']}/import",
            files={"file": ("a.csv", b"", "text/csv")},
            headers=team.h("builder"),
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/data-tables/{t['id']}/import",
            files={"file": ("a.csv", again, "text/csv")},
            headers=team.h("operator"),
        ).status_code
        == 403
    )
    exp = client.get(f"/api/v1/data-tables/{t['id']}/export.csv", headers=team.h("member"))
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    text = exp.content.decode("utf-8")
    assert text.startswith("﻿row_key,name,visits,vip,city") and "김민지" in text


def test_private_project_hides_table(client: TestClient, team: Team) -> None:
    proj = client.post(
        f"/api/v1/workspaces/{team.ws}/projects",
        json={"name": "비밀", "visibility": "private"},
        headers=team.h("builder"),
    ).json()
    t = make_table(client, team, "비밀 표", project_id=proj["id"])
    make_table(client, team, "공용 표")

    def names(role: str) -> set[str]:
        return {
            x["name"]
            for x in client.get(
                f"/api/v1/workspaces/{team.ws}/data-tables", headers=team.h(role)
            ).json()
        }

    assert names("builder") == {"비밀 표", "공용 표"}
    assert names("admin") == {"비밀 표", "공용 표"}
    assert names("operator") == {"공용 표"}
    assert (
        client.get(f"/api/v1/data-tables/{t['id']}", headers=team.h("operator")).status_code == 404
    )
    assert (
        client.get(f"/api/v1/data-tables/{t['id']}/rows", headers=team.h("member")).status_code
        == 404
    )


def test_row_limit(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_tables, "MAX_ROWS_PER_TABLE", 2)
    t = make_table(client, team)
    url = f"/api/v1/data-tables/{t['id']}/rows"
    for i in range(2):
        assert (
            client.post(
                url, json={"data": {"name": str(i)}}, headers=team.h("operator")
            ).status_code
            == 201
        )
    full = client.post(url, json={"data": {"name": "x"}}, headers=team.h("operator"))
    assert full.status_code == 409 and "2줄" in full.json()["detail"]["message"]


def test_other_workspace_cannot_see(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    t = make_table(client, team)
    assert client.get(f"/api/v1/data-tables/{t['id']}", headers=outsider).status_code == 404
    assert (
        client.get(f"/api/v1/workspaces/{team.ws}/data-tables", headers=outsider).status_code == 404
    )
