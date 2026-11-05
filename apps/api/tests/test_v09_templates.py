"""v0.9 마켓 템플릿 2개(제품 사진 만들기·주간 보고 엑셀): 검증을 통과하고 끝까지 실행된다."""

import io
import json
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v05_engine import make_app, start


def _template_graph(key: str) -> dict[str, Any]:
    path = pathlib.Path(__file__).resolve().parents[3] / "market-items" / key / "template.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _app(client: TestClient, team: Team, key: str, name: str) -> str:
    app_id = make_app(client, team, _template_graph(key), name=name)
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    return app_id


@pytest.mark.parametrize("key", ["tpl_product_image", "tpl_weekly_report_xlsx"])
def test_new_templates_validate(key: str) -> None:
    from api.engine.validator import ValidationEnv, validate_graph
    from nodes import registry

    res = validate_graph(_template_graph(key), ValidationEnv(registry=registry))
    assert res.valid, res.errors


def test_weekly_report_template_runs_end_to_end(client: TestClient, team: Team) -> None:
    app_id = _app(client, team, "tpl_weekly_report_xlsx", "주간 보고 템플릿")
    d = start(
        client,
        team,
        app_id,
        {"team": "영업1팀", "done": "- 견적서 발송\n계약서 검토\n\n• 고객 미팅"},
    )
    assert d["status"] == "succeeded", d["error"]
    assert "영업1팀 주간 보고.xlsx" in d["output"]["text"] and "3건" in d["output"]["text"]
    from openpyxl import load_workbook

    r = client.get(f"/api/v1/runs/{d['id']}/files/{d['files'][0]['id']}", headers=team.h("builder"))
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws is not None and ws.title == "주간 보고"
    assert [[c.value for c in row] for row in ws.iter_rows(min_row=1)] == [
        ["번호", "한 일"],
        ["1", "견적서 발송"],
        ["2", "계약서 검토"],
        ["3", "고객 미팅"],
    ]


def test_product_image_template_runs_with_fake_ai(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _app(client, team, "tpl_product_image", "사진 템플릿")
    d = start(client, team, app_id, {"message": "흰 배경 위의 빨간 머그컵"})
    assert d["status"] == "succeeded", d["error"]
    assert "사진 2장을 만들었어요" in d["output"]["text"] and len(d["files"]) == 2
    call = next(c for c in fake_llm.calls if c["kind"] == "image")
    assert "빨간 머그컵" in call["prompt"] and "글자는 넣지 않기" in call["prompt"]
