"""운영 준비 1차 B2: 개인정보 가리기(기록·AI 보내기 전)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import App, Conversation, Message, Run, RunStep
from api.services import pii
from api.tests.conftest import ROLES, Team
from api.tests.fakes import FakeAdapter

SAMPLE = (
    "홍길동 900101-1234567, 010-1234-5678, 02-345-6789, 카드 4111 1111 1111 1111, "
    "계좌 110-123-456789, 메일 a.b@ex.co.kr, 여권 M12345678"
)
LEAKS = (
    "900101-1234567",
    "010-1234-5678",
    "02-345-6789",
    "4111 1111 1111 1111",
    "110-123-456789",
    "a.b@ex.co.kr",
    "M12345678",
)


def test_mask_finds_korean_pii() -> None:
    out = pii.mask(SAMPLE)
    for leak in LEAKS:
        assert leak not in out, leak
    for kind in ("주민등록번호", "전화번호", "카드번호", "계좌번호", "이메일", "여권번호"):
        assert f"[{kind}]" in out
    assert out.startswith("홍길동 ")


@pytest.mark.parametrize(
    "text",
    [
        "날짜 2026-11-18, 시간 14:30",
        "주문번호 20261118001, 금액 1,234,000원",
        "카드 아닌 숫자 1234 5678 9012 3456",  # Luhn 실패
        "버전 1.2.3, 우편번호 06236",
    ],
)
def test_mask_leaves_normal_numbers(text: str) -> None:
    assert pii.mask(text) == text


def test_vault_round_trip() -> None:
    v = pii.Vault()
    masked = v.mask(SAMPLE)
    for leak in LEAKS:
        assert leak not in masked
    assert "[전화번호1]" in masked and "[전화번호2]" in masked
    # 같은 값은 같은 표시
    assert v.mask("다시 010-1234-5678") == "다시 [전화번호1]"
    answer = "고객([이메일1])께 [전화번호1]로 연락드릴게요."
    assert v.unmask(answer) == "고객(a.b@ex.co.kr)께 010-1234-5678로 연락드릴게요."
    assert v.unmask_value({"x": ["[여권번호1]"]}) == {"x": ["M12345678"]}


def test_mask_value_nested() -> None:
    out = pii.mask_value({"a": ["010-1111-2222", {"b": "x@y.com"}], "n": 3})
    assert out == {"a": ["[전화번호]", {"b": "[이메일]"}], "n": 3}


# ---------------- 설정 API ----------------
def test_privacy_settings_permissions(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/privacy"
    for role in ROLES:
        allowed = role in ("owner", "admin")
        assert (client.get(url, headers=team.h(role)).status_code == 200) == allowed, role
        r = client.patch(url, json={"mask_logs": True}, headers=team.h(role))
        assert (r.status_code == 200) == allowed, role
    got = client.patch(url, json={"mask_before_ai": True}, headers=team.h("owner")).json()
    assert got == {"mask_logs": True, "mask_before_ai": True}


# ---------------- 기록 화면 ----------------
def _app_run(team: Team) -> tuple[str, str]:
    with SessionLocal() as db:
        a = App(
            workspace_id=team.ws,
            name="개인정보",
            slug="pii",
            type="workflow",
            draft_graph={"version": 1, "nodes": [], "edges": [], "variables": {}},
            created_by=team.users["builder"],
        )
        db.add(a)
        db.commit()
        r = Run(
            app_id=a.id,
            status="succeeded",
            trigger="manual",
            input={"memo": SAMPLE},
            output={"text": "연락처 010-1234-5678"},
        )
        db.add(r)
        db.commit()
        db.add(
            RunStep(
                run_id=r.id,
                node_id="n1",
                status="succeeded",
                input={"q": "메일 a.b@ex.co.kr"},
                output={"text": "900101-1234567"},
                logs="",
            )
        )
        db.commit()
        return a.id, r.id


def test_run_views_masked_when_enabled(client: TestClient, team: Team) -> None:
    app_id, run_id = _app_run(team)
    detail = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    assert "010-1234-5678" in str(detail)  # 꺼져 있으면 그대로
    client.patch(
        f"/api/v1/workspaces/{team.ws}/privacy", json={"mask_logs": True}, headers=team.h("owner")
    )
    detail = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    listed = client.get(f"/api/v1/apps/{app_id}/runs", headers=team.h("builder")).json()
    ws_list = client.get(f"/api/v1/workspaces/{team.ws}/runs", headers=team.h("owner")).json()
    for body in (detail, listed, ws_list):
        text = str(body)
        for leak in LEAKS:
            assert leak not in text, leak
    assert detail["pii_masked"] is True
    # 저장된 원본은 그대로(되돌릴 수 있게 화면에서만 가린다)
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run is not None and "010-1234-5678" in str(run.output)


def test_conversation_masked_except_handoff(client: TestClient, team: Team) -> None:
    app_id, _ = _app_run(team)
    with SessionLocal() as db:
        convs = []
        for status in ("bot", "handoff"):
            c = Conversation(app_id=app_id, status=status)
            db.add(c)
            db.commit()
            db.add(Message(conversation_id=c.id, role="user", content="제 번호 010-9999-8888"))
            db.commit()
            convs.append(c.id)
    client.patch(
        f"/api/v1/workspaces/{team.ws}/privacy", json={"mask_logs": True}, headers=team.h("owner")
    )
    bot = client.get(f"/api/v1/conversations/{convs[0]}/messages", headers=team.h("operator"))
    handoff = client.get(f"/api/v1/conversations/{convs[1]}/messages", headers=team.h("operator"))
    assert bot.status_code == 200, bot.text
    assert "010-9999-8888" not in bot.text and "[전화번호]" in bot.text
    assert "010-9999-8888" in handoff.text
    listed = client.get(f"/api/v1/apps/{app_id}/conversations", headers=team.h("operator")).json()
    by_status = {c["status"]: c["first_question"] for c in listed}
    assert "010-9999-8888" not in by_status["bot"] and "010-9999-8888" in by_status["handoff"]


# ---------------- AI 보내기 전 ----------------
class SpyAdapter(FakeAdapter):
    """보낸 프롬프트를 기억하고, 가린 표시가 들어간 답을 돌려준다."""

    @property
    def seen(self) -> list[dict[str, Any]]:
        return self.calls

    def complete(self, **kw: Any) -> Any:
        res = super().complete(**kw)
        res.text = "확인했어요. [전화번호1]로 연락드릴게요."
        return res


def _services(team: Team) -> Any:
    from api.engine.executor import RunServices

    db = SessionLocal()
    return db, RunServices(db, team.ws)


def test_llm_masks_before_send_and_restores(
    team: Team, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from api.llm import registry as llm_registry

    spy = SpyAdapter()
    monkeypatch.setattr(llm_registry, "adapter_factory", lambda provider, key, base: spy)
    client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "openai",
            "label": "기본",
            "api_key": "sk-test-1234",
            "default_model": "gpt-test",
        },
        headers=team.h("owner"),
    )
    db, svc = _services(team)
    try:
        res = svc.llm_complete(
            provider="default",
            model=None,
            system="고객 응대",
            prompt="고객 연락처 010-1234-5678, 메일 a.b@ex.co.kr",
            temperature=None,
            json_schema=None,
            mask_pii=True,
        )
        sent = spy.seen[-1]
        assert "010-1234-5678" not in sent["prompt"] and "[전화번호1]" in sent["prompt"]
        assert "a.b@ex.co.kr" not in sent["prompt"]
        assert res.text == "확인했어요. 010-1234-5678로 연락드릴게요."
        assert "개인정보를 가리고 AI에 보냈어요." in svc.notes
        # 끄면 그대로 보낸다
        svc.llm_complete(
            provider="default",
            model=None,
            system="",
            prompt="010-1234-5678",
            temperature=None,
            json_schema=None,
        )
        assert spy.seen[-1]["prompt"] == "010-1234-5678"
    finally:
        db.close()


def test_workspace_setting_masks_all_ai_calls(
    team: Team, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from api.llm import registry as llm_registry

    spy = SpyAdapter()
    monkeypatch.setattr(llm_registry, "adapter_factory", lambda provider, key, base: spy)
    client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "openai",
            "label": "기본",
            "api_key": "sk-test-1234",
            "default_model": "m",
        },
        headers=team.h("owner"),
    )
    client.patch(
        f"/api/v1/workspaces/{team.ws}/privacy",
        json={"mask_before_ai": True},
        headers=team.h("owner"),
    )
    db, svc = _services(team)
    try:
        svc.llm_complete(
            provider="default",
            model=None,
            system="",
            prompt="주민번호 900101-1234567",
            temperature=None,
            json_schema=None,
        )
        assert "900101-1234567" not in spy.seen[-1]["prompt"]
    finally:
        db.close()


def test_llm_node_has_mask_option() -> None:
    from nodes import registry

    spec = registry.get("llm")
    assert spec is not None and "mask_pii" in spec.input_schema["properties"]
