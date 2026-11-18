"""운영 준비 1차 A6: 구조화 로그(JSON)와 /metrics."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.core import observability as obs
from api.tests.conftest import Team

TOKEN = "metrics-token-0123456789abcdef"  # noqa: S105


@pytest.fixture(autouse=True)
def _fresh() -> None:
    obs.reset()


def test_metrics_off_without_token(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 404


def test_metrics_requires_bearer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "genio_metrics_token", TOKEN)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


def test_metrics_count_requests_by_route_template(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "genio_metrics_token", TOKEN)
    client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("owner"))
    client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("owner"))
    client.get("/api/v1/apps/없는-앱", headers=team.h("owner"))
    body = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"}).text
    # 실제 id가 아니라 주소 틀로 센다(값 종류가 늘지 않게)
    assert (
        'genio_http_requests_total{method="GET",route="/workspaces/{ws}/members",status="2xx"} 2'
        in body
    )
    assert team.ws not in body
    assert 'route="/apps/{app_id}",status="4xx"' in body
    assert "genio_http_request_duration_seconds_count" in body
    assert 'genio_http_request_duration_seconds_bucket{le="+Inf"}' in body
    assert "genio_runs_running 0" in body and "genio_metrics_db_up 1" in body
    assert "genio_ai_cost_usd_month" in body


def test_json_log_line_has_request_id_and_hides_secrets() -> None:
    fmt = obs.JsonFormatter()
    token = obs.request_id_var.set("rid-123")
    try:
        rec = logging.LogRecord(
            "genio.x",
            logging.WARNING,
            __file__,
            1,
            "호출 실패 Authorization: Bearer sk-live-abcdef12",
            None,
            None,
        )
        line = json.loads(fmt.format(rec))
    finally:
        obs.request_id_var.reset(token)
    assert line["level"] == "WARNING" and line["logger"] == "genio.x"
    assert line["request_id"] == "rid-123"
    assert "sk-live-abcdef12" not in line["msg"]


def test_setup_logging_json(monkeypatch: pytest.MonkeyPatch) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        monkeypatch.setattr(get_settings(), "genio_log_format", "json")
        obs.setup_logging("test")
        assert isinstance(root.handlers[0].formatter, obs.JsonFormatter)
        monkeypatch.setattr(get_settings(), "genio_log_format", "text")
        obs.setup_logging("test")
        assert not isinstance(root.handlers[0].formatter, obs.JsonFormatter)
    finally:
        root.handlers = before


def test_label_escaping() -> None:
    assert obs._line("x", 1, {"route": 'a"b\\c'}) == 'x{route="a\\"b\\\\c"} 1'
