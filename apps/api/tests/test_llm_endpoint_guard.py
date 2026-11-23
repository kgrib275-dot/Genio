"""AI 연결 주소는 호출 직전에도 내부 IP를 막는다(DNS 리바인딩 방어)."""

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.core.crypto import encrypt_str
from api.db import SessionLocal
from api.llm.base import LlmError
from api.llm.registry import resolve_llm
from api.models import LlmProvider, Workspace
from api.tests.conftest import Team


def _provider(ws: str, base_url: str) -> None:
    with SessionLocal() as db:
        db.add(
            LlmProvider(
                workspace_id=ws,
                provider="openai-compatible",
                label="사내",
                api_key_encrypted=encrypt_str("k-secret"),
                base_url=base_url,
                default_model="m",
                is_default=True,
            )
        )
        db.commit()


def test_internal_endpoint_is_blocked_at_call_time(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, team: Team
) -> None:
    monkeypatch.setattr(get_settings(), "genio_allow_private_network", False)
    _provider(
        team.ws, "http://169.254.169.254/v1"
    )  # 연결을 만든 뒤 내부 주소로 바뀐 경우를 흉내 낸다
    with SessionLocal() as db, pytest.raises(LlmError) as exc:
        resolve_llm(db, team.ws)
    assert "허용할 내부 주소" in exc.value.hint
    assert "k-secret" not in str(exc.value)


def test_registered_internal_host_is_allowed(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, team: Team
) -> None:
    monkeypatch.setattr(get_settings(), "genio_allow_private_network", False)
    _provider(team.ws, "http://ai.corp.internal/v1")
    with SessionLocal() as db:
        w = db.get(Workspace, team.ws)
        assert w is not None
        w.settings = {**(w.settings or {}), "allow_private_hosts": ["ai.corp.internal"]}
        db.commit()
        llm = resolve_llm(db, team.ws)  # 관리자가 등록한 호스트는 통과한다
        assert llm.provider.base_url == "http://ai.corp.internal/v1"
