"""v0.5 마켓: 설치 업데이트, 템플릿 미리 보기·채울 빈칸, 분류, 새 커넥터 번들 검증."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.market.bundle import BundleError, read_manifest, validate_bundle
from api.market.service import items_dir
from api.models import ConnectorCredential, ConnectorDefinition, MarketItem
from api.tests.conftest import ROLES, Team, install

NEW_ITEMS = [
    "database",
    "http_credentials",
    "jandi",
    "naverworks",
    "kakao_alimtalk",
    "biz_inquiry_assign",
    "biz_weekly_report",
    "biz_onboarding_qa",
    "biz_quote_request",
    "biz_contract_review",
]


@pytest.mark.parametrize("key", NEW_ITEMS)
def test_new_bundles_validate(key: str) -> None:
    p = items_dir() / key
    validate_bundle(p, read_manifest(p))


def test_connector_without_permission_rejected(tmp_path: Path) -> None:
    (tmp_path / "connector.py").write_text("def a(p, s, n):\n    return {}\n", encoding="utf-8")
    manifest = {
        "key": "x",
        "type": "connector",
        "name": "x",
        "version": "1",
        "actions": [{"key": "a"}],
    }
    with pytest.raises(BundleError, match="도메인"):
        validate_bundle(tmp_path, manifest)
    validate_bundle(tmp_path, {**manifest, "database": True})
    validate_bundle(tmp_path, {**manifest, "actions": [], "credential_only": True})


def test_template_preview_and_category(client: TestClient, team: Team) -> None:
    d = client.get("/api/v1/market/items/biz_quote_request", headers=team.h("member")).json()
    pv = d["preview"]
    assert d["category"] == "업무" and pv["app_type"] == "workflow"
    assert [s["type"] for s in pv["steps"]][:3] == ["input", "parameter_extractor", "data_table"]
    assert pv["blanks"][0]["node_id"] == "n3" and "email" in pv["requires"]
    chat = client.get("/api/v1/market/items/biz_onboarding_qa", headers=team.h("member")).json()
    assert chat["preview"]["app_type"] == "chat"
    biz = client.get("/api/v1/market/items?category=업무", headers=team.h("member")).json()
    assert {i["key"] for i in biz} == {k for k in NEW_ITEMS if k.startswith("biz_")}
    msg = client.get("/api/v1/market/items?category=메신저", headers=team.h("member")).json()
    assert {"jandi", "naverworks", "kakao_alimtalk"} <= {i["key"] for i in msg}
    assert (
        "preview" not in client.get("/api/v1/market/items/slack", headers=team.h("member")).json()
    )


def test_installation_update(client: TestClient, team: Team) -> None:
    install(client, team, "slack")
    cred = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "slack", "name": "팀", "secrets": {"bot_token": "xoxb-1"}},
        headers=team.h("owner"),
    ).json()
    url = f"/api/v1/workspaces/{team.ws}/market/installations"
    inst = next(
        i for i in client.get(url, headers=team.h("member")).json() if i["item_key"] == "slack"
    )
    assert inst["update_available"] is False
    upd = f"{url}/{inst['id']}/update"
    assert client.post(upd, headers=team.h("owner")).status_code == 409  # 이미 최신

    with SessionLocal() as db:  # 마켓에 새 버전이 올라온 상황
        item = db.scalar(select(MarketItem).where(MarketItem.key == "slack"))
        assert item is not None
        item.version = "1.1.0"
        item.manifest = {**item.manifest, "version": "1.1.0"}
        db.commit()
    inst = next(
        i for i in client.get(url, headers=team.h("member")).json() if i["item_key"] == "slack"
    )
    assert inst["update_available"] is True and inst["latest_version"] == "1.1.0"
    for role in ("builder", "operator", "member"):
        assert client.post(upd, headers=team.h(role)).status_code == 403, role
    res = client.post(upd, headers=team.h("admin"))
    assert res.status_code == 200 and res.json()["version"] == "1.1.0", res.text
    assert res.json()["update_available"] is False
    with SessionLocal() as db:  # 연결 정보는 새 정의로 옮겨져 그대로 쓸 수 있다
        c = db.get(ConnectorCredential, cred["id"])
        assert c is not None
        d = db.get(ConnectorDefinition, c.definition_id)
        assert d is not None and d.version == "1.1.0"
    creds = client.get(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials", headers=team.h("builder")
    ).json()
    assert creds[0]["connector_key"] == "slack"
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).json()
    assert any(entry["action"] == "market.update" for entry in logs)
    assert ROLES
