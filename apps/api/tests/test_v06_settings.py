"""v0.6 AI 연결 테스트(모델 목록 불러오기)와 목록 설정(계정별 유지)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.llm import probe
from api.llm.base import LlmError
from api.tests.conftest import ROLES, Team, add_llm

SECRET = "sk-test-secret-abcd1234"  # noqa: S105


def _fake_get(calls: list[dict[str, Any]]) -> Any:
    def fake(url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> Any:
        calls.append({"url": url, "headers": headers, "params": params})
        if "anthropic" in url:
            return {"data": [{"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"}]}
        if "generativelanguage" in url:
            return {
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "displayName": "Gemini 2.5 Flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/text-embedding-004",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            }
        return {"data": [{"id": "gpt-5.4-mini"}, {"id": "whisper-1"}, {"id": "deepseek-chat"}]}

    return fake


def test_probe_new_key(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(probe, "_get", _fake_get(calls))
    url = f"/api/v1/workspaces/{team.ws}/llm-providers/test"
    r = client.post(url, json={"provider": "anthropic", "api_key": SECRET}, headers=team.h("owner"))
    assert r.status_code == 200 and r.json()["ok"]
    assert r.json()["models"] == [{"model": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"}]
    assert calls[-1]["headers"]["x-api-key"] == SECRET
    r = client.post(url, json={"provider": "google", "api_key": SECRET}, headers=team.h("owner"))
    assert [m["model"] for m in r.json()["models"]] == ["gemini-2.5-flash"]
    r = client.post(url, json={"provider": "deepseek", "api_key": SECRET}, headers=team.h("admin"))
    body = r.json()
    assert body["ok"] and [m["model"] for m in body["models"]] == ["deepseek-chat", "gpt-5.4-mini"]
    assert calls[-1]["url"].endswith("/models") and "deepseek" in calls[-1]["url"]
    assert SECRET not in r.text


def test_probe_failure_is_two_lines(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(*a: Any, **k: Any) -> Any:
        raise LlmError("API 키가 맞지 않거나 권한이 없어요.", "키를 다시 복사해 넣어 보세요.")

    monkeypatch.setattr(probe, "_get", bad)
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/test",
        json={"provider": "openai", "api_key": SECRET},
        headers=team.h("owner"),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["message"] and r.json()["hint"]
    assert SECRET not in r.text


@pytest.mark.parametrize("role", ROLES)
def test_probe_permissions(
    client: TestClient, team: Team, role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "_get", _fake_get([]))
    prov = add_llm(client, team)
    new = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/test",
        json={"provider": "openai", "api_key": SECRET},
        headers=team.h(role),
    )
    saved = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{prov['id']}/test", headers=team.h(role)
    )
    assert (new.status_code == 200) == (role in ("owner", "admin"))
    assert (saved.status_code == 200) == (role in ("owner", "admin", "builder"))
    if saved.status_code == 200:
        assert saved.json()["ok"] and SECRET not in saved.text


def test_list_prefs_are_per_user_and_merge(client: TestClient, team: Team) -> None:
    h = team.h("builder")
    r = client.patch(
        "/api/v1/me", json={"preferences": {"lists": {"apps": {"size": 50}}}}, headers=h
    )
    assert r.status_code == 200
    client.patch(
        "/api/v1/me",
        json={"preferences": {"lists": {"runs": {"filters": {"status": "failed"}}}}},
        headers=h,
    )
    client.patch(
        "/api/v1/me",
        json={"preferences": {"lists": {"apps": {"filters": {"type": "chat"}}}}},
        headers=h,
    )
    lists = client.get("/api/v1/me", headers=h).json()["preferences"]["lists"]
    assert lists["apps"] == {"size": 50, "filters": {"type": "chat"}}
    assert lists["runs"] == {"filters": {"status": "failed"}}
    # 다른 사람에게는 보이지 않는다
    assert client.get("/api/v1/me", headers=team.h("member")).json()["preferences"]["lists"] == {}
    bad = client.patch(
        "/api/v1/me", json={"preferences": {"lists": {"apps": {"size": 7}}}}, headers=h
    )
    assert bad.status_code == 422
