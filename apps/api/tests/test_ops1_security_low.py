"""운영 준비 1차 B1(낮음): F12 정규식, F13 공개 첨부 범위, F14 공개 오류 문구, F15 멤버 목록,
F17 이벤트 재전송, F18 새로고침 토큰 회전, F20 비밀 키."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import Settings, secret_key_problem
from api.db import SessionLocal
from api.models import UserSession
from api.routers.deployments import public_error_detail
from api.services import kb_pipeline
from api.services import service_events as sev
from api.services.kb_pipeline import PipelineError, regex_risky
from api.tests.conftest import PASSWORD, ROLES, Team
from api.tests.test_v09_service_events import gh_body, gh_headers, runs_of, setup


# ---------------- F12 ----------------
@pytest.mark.parametrize(
    "pattern",
    ["(a+)+$", "(a|b*)*", "(x{2,})+", "((ab)*)+", r"(\w+)\s\1", "(?P<a>x)(?P=a)", r"(\d+){2,}"],
)
def test_risky_regex_rejected(pattern: str) -> None:
    assert regex_risky(pattern)
    raw = [{"type": "clean", "enabled": True, "remove_patterns": [pattern]}]
    with pytest.raises(PipelineError):
        kb_pipeline.normalize_pipeline(raw)


@pytest.mark.parametrize(
    "pattern",
    [
        r"페이지 \d+",
        r"^\s*-\s*\d+\s*-\s*$",
        "(ab)+",
        r"(\d+)-(\d+)",
        r"(?P<부서>[^_]+)_(?P<연도>\d{4})",
    ],
)
def test_normal_regex_allowed(pattern: str) -> None:
    assert not regex_risky(pattern)


def test_old_risky_pattern_skipped_at_run() -> None:
    out = kb_pipeline.clean_text("aaaa 페이지 3", {"remove_patterns": ["(a+)+$", r"페이지 \d+"]})
    assert "페이지" not in out and "aaaa" in out


# ---------------- F14 ----------------
def test_public_error_hides_internal_details() -> None:
    raw = (
        "외부 호출 실패: http://10.0.0.5:8080/admin?token=abc 에서 오류, "
        "담당 ops@corp.example, 서버 192.168.1.20:5432, Authorization: Bearer sk-live-123456"
    )
    out = public_error_detail(raw)
    for leak in ("10.0.0.5", "ops@corp.example", "192.168.1.20", "sk-live-123456", "token=abc"):
        assert leak not in out, leak
    assert "[주소]" in out and len(out) <= 200
    assert public_error_detail(None) == ""


# ---------------- F15 ----------------
def test_member_list_by_role(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/members"
    for role in ROLES:
        rows = client.get(url, headers=team.h(role)).json()
        assert len(rows) == len(ROLES)
        sample = rows[0]
        if role in ("owner", "admin"):
            assert "two_factor" in sample and "@test.local" in sample["email"]
        else:
            assert "two_factor" not in sample and "only_here" not in sample
            if role == "builder":
                assert sample["email"].endswith("@test.local") and "***" not in sample["email"]
            else:
                assert all("***@" in r["email"] for r in rows)
        assert all(r["name"] for r in rows)


# ---------------- F17 ----------------
@pytest.fixture(autouse=True)
def _fresh_seen() -> None:
    sev.reset_seen()


def test_github_replay_with_new_delivery_id_ignored(client: TestClient, team: Team) -> None:
    app_id, _, path, secret = setup(client, team, "github")
    body = gh_body()
    assert (
        client.post(
            path, content=body, headers=gh_headers(secret, body, delivery="d-1")
        ).status_code
        == 202
    )
    # 서명된 본문은 그대로, 배달 번호만 바꿔 다시 보낸다
    again = client.post(path, content=body, headers=gh_headers(secret, body, delivery="d-2"))
    assert again.status_code == 200 and "같은 내용" in again.json()["ignored"]
    other = gh_body(title="다른 이슈")
    assert (
        client.post(
            path, content=other, headers=gh_headers(secret, other, delivery="d-3")
        ).status_code
        == 202
    )
    assert len(runs_of(app_id)) == 2


def test_body_key_only_for_untimed_services() -> None:
    assert sev.body_replay_key("github", "t", b"x")
    assert sev.body_replay_key("slack", "t", b"x") is None


# ---------------- F18 ----------------
def _login(client: TestClient, role: str = "member") -> dict[str, Any]:
    r = client.post(
        "/api/v1/auth/login", json={"email": f"{role}@test.local", "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    tokens: dict[str, Any] = r.json()
    return tokens


def _refresh(client: TestClient, token: str) -> Any:
    return client.post("/api/v1/auth/refresh", json={"refresh_token": token})


def test_refresh_rotates_and_detects_reuse(client: TestClient, team: Team) -> None:
    first = _login(client)
    r1 = _refresh(client, first["refresh_token"])
    assert r1.status_code == 200
    second = r1.json()
    assert second["refresh_token"] != first["refresh_token"]
    r2 = _refresh(client, second["refresh_token"])
    assert r2.status_code == 200
    third = r2.json()
    # 이미 두 번 전에 바뀐 토큰이 다시 오면(도난 의심) 그 기기 로그인을 끊는다
    stolen = _refresh(client, first["refresh_token"])
    assert stolen.status_code == 401 and "끊었어요" in stolen.text
    assert _refresh(client, third["refresh_token"]).status_code == 401
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {third['access_token']}"})
    assert me.status_code == 401


def test_concurrent_tabs_grace(client: TestClient, team: Team) -> None:
    first = _login(client)
    assert _refresh(client, first["refresh_token"]).status_code == 200
    # 다른 탭이 같은 옛 토큰으로 바로(30초 안) 새로고침해도 받아 준다
    assert _refresh(client, first["refresh_token"]).status_code == 200


def test_grace_expires(client: TestClient, team: Team) -> None:
    first = _login(client)
    second = _refresh(client, first["refresh_token"]).json()
    with SessionLocal() as db:
        sess = db.query(UserSession).filter(UserSession.refresh_jti.is_not(None)).first()
        assert sess is not None
        sess.refresh_rotated_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()
    assert _refresh(client, first["refresh_token"]).status_code == 401
    assert _refresh(client, second["refresh_token"]).status_code == 401


# ---------------- F20 ----------------
def test_secret_key_problem() -> None:
    assert secret_key_problem(Settings(genio_secret_key="dev-secret-change-me-please-32bytes!!"))  # noqa: S106
    assert secret_key_problem(Settings(genio_secret_key="change-me-to-a-long-random-string"))  # noqa: S106
    assert secret_key_problem(Settings(genio_secret_key="short"))  # noqa: S106
    assert secret_key_problem(Settings(genio_secret_key="x" * 40)) is None


def test_production_refuses_default_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main
    from api.config import get_settings

    st = get_settings()
    monkeypatch.setattr(st, "genio_secret_key", "change-me-to-a-long-random-string")
    monkeypatch.setattr(st, "genio_env", "production")
    with pytest.raises(RuntimeError, match="GENIO_SECRET_KEY"):
        main.check_secret_key()
    monkeypatch.setattr(st, "genio_env", "dev")
    monkeypatch.setattr(
        st, "genio_public_web_url", "http://localhost:5190"
    )  # .env의 공개 주소와 무관하게
    main.check_secret_key()  # 개발 모드는 경고만
    # 공개 주소를 쓰면 GENIO_ENV가 dev여도 운영으로 보고 멈춘다
    monkeypatch.setattr(st, "genio_public_web_url", "https://genio.example.com")
    with pytest.raises(RuntimeError, match="GENIO_SECRET_KEY"):
        main.check_secret_key()
