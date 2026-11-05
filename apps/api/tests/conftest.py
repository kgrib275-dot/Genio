from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.core import ratelimit
from api.core.security import create_tokens, hash_password
from api.db import Base, SessionLocal, engine
from api.llm import keypool
from api.llm import registry as llm_registry
from api.main import app
from api.market.service import sync_catalog
from api.models import Membership, Organization, User, Workspace
from api.tests.fakes import FakeAdapter

ROLES = ("owner", "admin", "builder", "operator", "member")
PASSWORD = "password123!"  # noqa: S105


@pytest.fixture(autouse=True)
def fresh_db() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ratelimit.reset()
    keypool.reset()
    with SessionLocal() as db:
        sync_catalog(db)
    yield


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeAdapter:
    adapter = FakeAdapter()
    monkeypatch.setattr(llm_registry, "adapter_factory", lambda provider, key, base: adapter)
    return adapter


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@dataclass
class Team:
    ws: str
    users: dict[str, str]  # role -> user_id
    tokens: dict[str, str]  # role -> access token

    def h(self, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[role]}"}


@pytest.fixture
def team() -> Team:
    with SessionLocal() as db:
        org = Organization(name="테스트", slug="test-org")
        db.add(org)
        db.flush()
        ws = Workspace(org_id=org.id, name="테스트 워크스페이스", slug="test-ws", settings={})
        db.add(ws)
        db.flush()
        users: dict[str, str] = {}
        pw = hash_password(PASSWORD)
        for role in ROLES:
            u = User(email=f"{role}@test.local", name=f"{role} 사용자", password_hash=pw)
            db.add(u)
            db.flush()
            db.add(Membership(user_id=u.id, workspace_id=ws.id, role=role))
            users[role] = u.id
        db.commit()
        ws_id = ws.id
    tokens = {role: create_tokens(uid)["access_token"] for role, uid in users.items()}
    return Team(ws=ws_id, users=users, tokens=tokens)


@pytest.fixture
def outsider() -> dict[str, str]:
    with SessionLocal() as db:
        u = User(email="outsider@test.local", name="외부인", password_hash=hash_password(PASSWORD))
        db.add(u)
        db.commit()
        token = create_tokens(u.id)["access_token"]
    return {"Authorization": f"Bearer {token}"}


def add_llm(
    client: TestClient, team: Team, provider: str = "anthropic", model: str = "claude-sonnet-5-5"
) -> dict[str, Any]:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": provider,
            "label": "기본 AI",
            "api_key": "sk-test-secret-abcd1234",
            "default_model": model,
            "is_default": True,
        },
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


def install(client: TestClient, team: Team, key: str) -> None:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/market/install",
        json={"item_key": key},
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text


def membership_id(team: Team, role: str) -> str:
    with SessionLocal() as db:
        m = db.scalar(select(Membership).where(Membership.user_id == team.users[role]))
        assert m is not None
        return m.id
