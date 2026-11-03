"""샘플 10가지: 넣기(한 번만), 권한, 그리고 AI 키 없이 도는 샘플은 실제로 끝까지 실행되는지."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.tests.conftest import Team


def _apps(client: TestClient, team: Team) -> dict[str, dict[str, Any]]:
    st = client.get(f"/api/v1/workspaces/{team.ws}/samples", headers=team.h("member")).json()
    return {a["name"].split(" ", 1)[0]: a for a in st["apps"]}


def _run(client: TestClient, team: Team, app_id: str, inp: dict[str, Any]) -> dict[str, Any]:
    r = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": inp}, headers=team.h("builder"))
    assert r.status_code == 201, r.text
    detail: dict[str, Any] = client.get(
        f"/api/v1/runs/{r.json()['id']}", headers=team.h("builder")
    ).json()
    return detail


def test_install_once_and_permissions(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/samples"
    assert client.get(url, headers=team.h("member")).json()["installed"] is False
    for role in ("operator", "member"):
        assert client.post(url, headers=team.h(role)).status_code == 403
    out = client.post(url, headers=team.h("builder"))
    assert out.status_code == 201
    assert len(out.json()["apps"]) == 10
    again = client.post(url, headers=team.h("admin"))
    assert again.status_code == 409 and "샘플 체험" in again.json()["detail"]["hint"]
    tables = client.get(
        f"/api/v1/workspaces/{team.ws}/data-tables", headers=team.h("member")
    ).json()
    assert {t["name"] for t in tables} >= {"고객 명부", "주문", "휴가 기록"}


def test_keyless_samples_run(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post(f"/api/v1/workspaces/{team.ws}/samples", headers=team.h("owner"))
    apps = _apps(client, team)

    # ③ 고객 명부 저장
    d = _run(client, team, apps["③"]["id"], {"name": "오지호", "phone": "010-9999-0000"})
    assert d["status"] == "succeeded" and "9명" in d["output"]["text"]
    # ④ 아침 보고
    d = _run(client, team, apps["④"]["id"], {"memo": ""})
    assert d["status"] == "succeeded" and "전체 주문: 5건" in d["output"]["text"]
    assert "처리 대기(접수): 3건" in d["output"]["text"]
    # ⑤ 주문 접수(값 정리로 금액 계산)
    d = _run(client, team, apps["⑤"]["id"], {"product": "웹캠", "qty": 2, "price": 59000})
    assert d["status"] == "succeeded" and "118000" in d["output"]["text"]
    # ⑥ 환율(외부 호출은 가짜로)
    monkeypatch.setattr(
        safe_http,
        "request",
        lambda method, url, *, headers, body: {
            "status": 200,
            "body": {"date": "2026-11-03", "rates": {"KRW": 1380.5}},
        },
    )
    d = _run(client, team, apps["⑥"]["id"], {"currency": "USD"})
    assert d["status"] == "succeeded" and "1380.5" in d["output"]["text"]
    # ⑦ 견적: 작은 견적 / 큰 견적(결재)
    d = _run(client, team, apps["⑦"]["id"], {"qty": 3, "unit_price": 45000, "discount_code": ""})
    assert d["status"] == "succeeded" and "148500" in d["output"]["text"]
    d = _run(
        client,
        team,
        apps["⑦"]["id"],
        {"qty": 40, "unit_price": 30000, "discount_code": "welcome10"},
    )
    assert d["status"] == "succeeded" and "결재" in d["output"]["text"]
    # ② 휴가 신청: 승인 대기 → 승인 → 표에 기록
    d = _run(
        client, team, apps["②"]["id"], {"message": "가족 행사", "start": "2026-12-01", "days": 1}
    )
    assert d["status"] == "waiting_approval"
    ok = client.post(
        f"/api/v1/runs/{d['id']}/approve",
        json={"approved": True, "comment": "잘 다녀오세요"},
        headers=team.h("admin"),
    )
    assert ok.status_code == 200, ok.text
    d = client.get(f"/api/v1/runs/{d['id']}", headers=team.h("builder")).json()
    assert d["status"] == "succeeded" and "잘 다녀오세요" in d["output"]["text"]
    # 문장 설명(S3)
    assert d["story"] and all(isinstance(x, str) for x in d["story"])
