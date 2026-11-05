"""v0.9 AI 키 분산·돌려쓰기, 공급자 간 자동 전환, 재정렬 전용 모델."""

import io
import random
from collections import Counter
from collections.abc import Callable
from typing import Any

import httpx
import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.engine.pricing import cost_of
from api.llm import keypool, rerank
from api.llm import registry as llm_registry
from api.llm.base import (
    KIND_AUTH,
    KIND_CONTENT_FILTER,
    KIND_CONTEXT,
    KIND_OTHER,
    KIND_OUTAGE,
    KIND_RATE_LIMIT,
    ChatTurn,
    LlmError,
    OnText,
    ToolDef,
)
from api.llm.chain import DEFAULT_TRIGGERS, ChainAdapter
from api.llm.registry import resolve_llm
from api.models import LlmProvider, Run
from api.services.app_config import DEFAULT_FEATURES
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v05_engine import make_app, start
from nodes import LlmResult

# ---------------------------------------------------------------- 가짜 공급자 세계
Rule = Callable[[str, OnText | None], LlmResult]


def ok(text: str = "좋아요", tokens: tuple[int, int] = (100, 20)) -> Rule:
    def rule(model: str, on_delta: OnText | None) -> LlmResult:
        return LlmResult(text=text, model=model, input_tokens=tokens[0], output_tokens=tokens[1])

    return rule


def fail(kind: str, message: str = "실패했어요") -> Rule:
    def rule(model: str, on_delta: OnText | None) -> LlmResult:
        raise LlmError(message, "잠시 후 다시 시도하세요.", retryable=True, kind=kind)

    return rule


def stream_then_fail(kind: str) -> Rule:
    def rule(model: str, on_delta: OnText | None) -> LlmResult:
        if on_delta is not None:
            on_delta("안녕")
        raise LlmError("중간에 끊겼어요", "다시 시도하세요.", retryable=True, kind=kind)

    return rule


class World:
    """(공급자, 키)마다 동작을 정하고 불린 순서를 기록한다."""

    def __init__(self) -> None:
        self.rules: dict[tuple[str, str], Rule] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.chat_messages: list[tuple[str, list[dict[str, Any]]]] = []


class FakeProv:
    def __init__(self, world: World, provider: str, key: str) -> None:
        self.world = world
        self.provider = provider
        self.key = key

    def _run(self, model: str, on_delta: OnText | None) -> LlmResult:
        self.world.calls.append((self.provider, self.key, model))
        return self.world.rules.get((self.provider, self.key), ok())(model, on_delta)

    def complete(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
        on_delta: OnText | None = None,
        images: Any = None,
    ) -> LlmResult:
        res = self._run(model, on_delta)
        if json_schema is not None and res.data is None:
            res.data = {"ok": True}
        return res

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn:
        self.world.chat_messages.append((self.provider, messages))
        res = self._run(model, on_text)
        return ChatTurn(
            text=res.text,
            model=res.model,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
        )

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        self.world.calls.append((self.provider, self.key, model))
        return [[0.0] * 8 for _ in texts]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    monkeypatch.setattr(
        llm_registry, "adapter_factory", lambda provider, key, base: FakeProv(w, provider, key)
    )
    return w


# ---------------------------------------------------------------- 도우미
def conn(
    client: TestClient,
    team: Team,
    provider: str,
    label: str,
    model: str,
    key: str,
    *,
    default: bool = False,
    base_url: str | None = None,
) -> str:
    body: dict[str, Any] = {
        "provider": provider,
        "label": label,
        "api_key": key,
        "default_model": model,
        "is_default": default,
    }
    if base_url:
        body["base_url"] = base_url
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers", json=body, headers=team.h("owner")
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


def add_key(
    client: TestClient, team: Team, cid: str, key: str, label: str = "", weight: int = 1
) -> str:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{cid}/keys",
        json={"label": label, "api_key": key, "weight": weight},
        headers=team.h("owner"),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["keys"][-1]["id"])


def set_strategy(client: TestClient, team: Team, cid: str, strategy: str) -> None:
    r = client.patch(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{cid}",
        json={"key_strategy": strategy},
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text


def put_fallback(
    client: TestClient,
    team: Team,
    links: list[tuple[str, str]],
    *,
    enabled: bool = True,
    triggers: dict[str, bool] | None = None,
) -> None:
    r = client.put(
        f"/api/v1/workspaces/{team.ws}/llm-fallback",
        json={
            "enabled": enabled,
            "links": [{"provider_id": pid, "model": model} for pid, model in links],
            "triggers": triggers or {},
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text


def call(team: Team, **kw: Any) -> tuple[LlmResult, Any]:
    with SessionLocal() as db:
        llm = resolve_llm(db, team.ws, "default")
        res = llm.adapter.complete(
            model=llm.model,
            system="시스템",
            prompt="안녕",
            temperature=None,
            json_schema=kw.get("json_schema"),
            on_delta=kw.get("on_delta"),
            images=kw.get("images"),
        )
        return res, llm.adapter


# ---------------------------------------------------------------- A. 키 돌려쓰기
def test_round_robin_cycles_keys(client: TestClient, team: Team, world: World) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-bbbb-0002", "둘째")
    add_key(client, team, cid, "sk-cccc-0003", "셋째")
    set_strategy(client, team, cid, "round_robin")
    firsts = []
    for _ in range(6):
        world.calls.clear()
        call(team)
        firsts.append(world.calls[0][1])
    assert firsts == ["sk-aaaa-0001", "sk-bbbb-0002", "sk-cccc-0003"] * 2


def test_weighted_distribution_follows_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keypool, "rng", random.Random(7))  # noqa: S311 - 시험용 고정 시드
    keys = [
        keypool.KeyRef("a", "가", "s1", 8, 1),
        keypool.KeyRef("b", "나", "s2", 1, 2),
        keypool.KeyRef("c", "다", "s3", 1, 3),
    ]
    first = Counter(keypool.order("conn-w", keys, "weighted")[0].id for _ in range(2000))
    assert 0.74 < first["a"] / 2000 < 0.86
    assert first["b"] > 0 and first["c"] > 0
    # 모든 키가 순서에 한 번씩 들어 있다
    assert {k.id for k in keypool.order("conn-w", keys, "weighted")} == {"a", "b", "c"}


def test_failover_rate_limit_cooldown_expires(
    client: TestClient, team: Team, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = [1000.0]
    monkeypatch.setattr(keypool, "clock", lambda: t[0])
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-bbbb-0002", "둘째")
    world.rules[("openai", "sk-aaaa-0001")] = fail(KIND_RATE_LIMIT)
    res, adapter = call(team)
    assert [c[1] for c in world.calls] == ["sk-aaaa-0001", "sk-bbbb-0002"] and res.text == "좋아요"
    assert adapter.take_notes() == ["키 1번을 쓸 수 없어 키 2번으로 바꿔 다시 시도했어요."]
    # 쉬는 동안에는 첫 키를 건너뛴다
    world.calls.clear()
    call(team)
    assert [c[1] for c in world.calls] == ["sk-bbbb-0002"]
    # 61초가 지나면 다시 첫 키부터
    t[0] += 61
    world.calls.clear()
    call(team)
    assert world.calls[0][1] == "sk-aaaa-0001"


def test_auth_error_rests_long_until_key_test(
    client: TestClient, team: Team, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.llm import probe

    t = [5000.0]
    monkeypatch.setattr(keypool, "clock", lambda: t[0])
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-bbbb-0002")
    world.rules[("openai", "sk-aaaa-0001")] = fail(KIND_AUTH, "키가 틀렸어요")
    call(team)
    t[0] += 600  # 10분 뒤에도 쉬는 중
    world.calls.clear()
    call(team)
    assert [c[1] for c in world.calls] == ["sk-bbbb-0002"]
    # 키를 고쳤다고 치고 '연결 테스트'가 성공하면 바로 다시 쓴다
    world.rules.pop(("openai", "sk-aaaa-0001"))
    monkeypatch.setattr(probe, "_get", lambda *a, **k: {"data": [{"id": "gpt-4o-mini"}]})
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{cid}/keys/primary/test",
        headers=team.h("builder"),
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    world.calls.clear()
    call(team)
    assert world.calls[0][1] == "sk-aaaa-0001"


def test_all_keys_failing_raises_last_error_without_secrets(
    client: TestClient, team: Team, world: World
) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-bbbb-0002")
    world.rules[("openai", "sk-aaaa-0001")] = fail(KIND_RATE_LIMIT, "한도 초과(첫째)")
    world.rules[("openai", "sk-bbbb-0002")] = fail(KIND_RATE_LIMIT, "한도 초과(둘째)")
    with pytest.raises(LlmError) as exc:
        call(team)
    assert exc.value.kind == KIND_RATE_LIMIT and exc.value.message == "한도 초과(둘째)"
    assert "sk-" not in exc.value.message + exc.value.hint
    # 첫째·둘째 모두 시도했다
    assert [c[1] for c in world.calls] == ["sk-aaaa-0001", "sk-bbbb-0002"]


def test_non_key_errors_do_not_rotate(client: TestClient, team: Team, world: World) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-bbbb-0002")
    world.rules[("openai", "sk-aaaa-0001")] = fail(KIND_OUTAGE)
    with pytest.raises(LlmError):
        call(team)
    assert [c[1] for c in world.calls] == ["sk-aaaa-0001"]  # 서버 문제는 키를 바꿔도 소용없다


def test_keys_are_masked_and_encrypted(client: TestClient, team: Team) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    add_key(client, team, cid, "sk-secret-bbbb-0002", "둘째", 3)
    r = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("builder"))
    assert r.status_code == 200
    assert "sk-aaaa-0001" not in r.text and "sk-secret-bbbb-0002" not in r.text
    keys = r.json()[0]["keys"]
    assert [k["masked"] for k in keys] == ["****0001", "****0002"]
    assert keys[1]["label"] == "둘째" and keys[1]["weight"] == 3 and keys[0]["primary"] is True
    with SessionLocal() as db:
        row = db.get(LlmProvider, cid)
        assert row is not None
        stored = row.extra_keys[0]["key_encrypted"]
        assert "secret-bbbb" not in stored  # 암호화돼 저장


def test_key_rules_and_validation(client: TestClient, team: Team) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    base = f"/api/v1/workspaces/{team.ws}/llm-providers/{cid}"
    h = team.h("owner")
    # 기본 키는 끄거나 지울 수 없다(두 줄 오류)
    for method, path, body in (
        ("patch", f"{base}/keys/primary", {"disabled": True}),
        ("delete", f"{base}/keys/primary", None),
    ):
        r = client.request(method, path, json=body, headers=h)
        assert r.status_code == 409, (method, r.text)
        d = r.json()["detail"]
        assert d["message"] and d["hint"]
    assert client.patch(f"{base}", json={"key_strategy": "아무거나"}, headers=h).status_code == 422
    assert client.patch(f"{base}/keys/primary", json={"weight": 0}, headers=h).status_code == 422
    assert client.patch(f"{base}/keys/nope", json={"weight": 2}, headers=h).status_code == 404
    # 최대 10개
    for i in range(9):
        add_key(client, team, cid, f"sk-extra-{i:04d}")
    r = client.post(f"{base}/keys", json={"api_key": "sk-extra-9999"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["hint"]
    # 끄기·비중 바꾸기·지우기
    view = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=h).json()[0]
    kid = view["keys"][1]["id"]
    r = client.patch(f"{base}/keys/{kid}", json={"disabled": True, "weight": 5}, headers=h)
    k = next(x for x in r.json()["keys"] if x["id"] == kid)
    assert k["disabled"] is True and k["weight"] == 5
    assert client.delete(f"{base}/keys/{kid}", headers=h).status_code == 204
    assert (
        len(client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=h).json()[0]["keys"])
        == 9
    )


def test_disabled_key_is_skipped(client: TestClient, team: Team, world: World) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    kid = add_key(client, team, cid, "sk-bbbb-0002")
    set_strategy(client, team, cid, "round_robin")
    client.patch(
        f"/api/v1/workspaces/{team.ws}/llm-providers/{cid}/keys/{kid}",
        json={"disabled": True},
        headers=team.h("owner"),
    )
    for _ in range(3):
        world.calls.clear()
        call(team)
        assert world.calls[0][1] == "sk-aaaa-0001"


@pytest.mark.parametrize("role", ROLES)
def test_key_and_fallback_permissions(
    client: TestClient, team: Team, role: str, world: World
) -> None:
    cid = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-aaaa-0001", default=True)
    other = conn(client, team, "anthropic", "대체", "claude-sonnet-5-5", "sk-ant-0002")
    base = f"/api/v1/workspaces/{team.ws}"
    h = team.h(role)
    manage = role in ("owner", "admin")
    build = role in ("owner", "admin", "builder")
    assert (client.get(f"{base}/llm-providers", headers=h).status_code == 200) == build
    assert (
        client.post(
            f"{base}/llm-providers/{cid}/keys", json={"api_key": "sk-new-12345"}, headers=h
        ).status_code
        == 201
    ) == manage
    assert (
        client.patch(
            f"{base}/llm-providers/{cid}", json={"key_strategy": "weighted"}, headers=h
        ).status_code
        == 200
    ) == manage
    assert (client.get(f"{base}/llm-fallback", headers=h).status_code == 200) == build
    put = client.put(
        f"{base}/llm-fallback",
        json={"enabled": True, "links": [{"provider_id": other}]},
        headers=h,
    )
    assert (put.status_code == 200) == manage
    assert (client.post(f"{base}/llm-fallback/test", headers=h).status_code == 200) == manage
    assert (client.get(f"{base}/rerank-connections", headers=h).status_code == 200) == build
    t = client.post(f"{base}/llm-providers/{cid}/keys/primary/test", headers=h)
    assert (t.status_code == 200) == build


def test_other_workspace_connection_is_404(client: TestClient, team: Team) -> None:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers/not-mine/keys",
        json={"api_key": "sk-new-12345"},
        headers=team.h("owner"),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- B. 공급자 간 자동 전환
def _chain(client: TestClient, team: Team, **kw: Any) -> tuple[str, str]:
    a = conn(client, team, "openai", "메인 GPT", "gpt-4o-mini", "sk-oa-0001", default=True)
    b = conn(client, team, "anthropic", "대체 Claude", "claude-sonnet-5-5", "sk-ant-0002")
    put_fallback(client, team, [(b, "")], **kw)
    return a, b


@pytest.mark.parametrize(
    ("kind", "flag", "expect"),
    [
        (KIND_OUTAGE, None, True),
        (KIND_RATE_LIMIT, None, True),
        (KIND_CONTENT_FILTER, None, False),
        (KIND_CONTENT_FILTER, "content_filter", True),
        (KIND_CONTEXT, None, False),
        (KIND_CONTEXT, "context_length", True),
        (KIND_AUTH, None, False),
        (KIND_AUTH, "auth", True),
        (KIND_OTHER, None, False),
    ],
)
def test_fallback_triggers(
    client: TestClient, team: Team, world: World, kind: str, flag: str | None, expect: bool
) -> None:
    _chain(client, team, triggers={flag: True} if flag else None)
    world.rules[("openai", "sk-oa-0001")] = fail(kind, "첫 연결 실패")
    if expect:
        res, adapter = call(team)
        assert res.model == "claude-sonnet-5-5" and res.text == "좋아요"
        notes = adapter.take_notes()
        assert "대체 연결(대체 Claude)로 답했어요." in notes
    else:
        with pytest.raises(LlmError) as exc:
            call(team)
        assert exc.value.message == "첫 연결 실패"
        assert not any(c[0] == "anthropic" for c in world.calls)  # 대체 연결은 부르지 않았다


def test_rate_limit_falls_back_only_after_keys_exhausted(
    client: TestClient, team: Team, world: World
) -> None:
    a, _ = _chain(client, team)
    add_key(client, team, a, "sk-oa-0002")
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_RATE_LIMIT)
    world.rules[("openai", "sk-oa-0002")] = ok("둘째 키가 답함")
    res, _ = call(team)
    assert res.text == "둘째 키가 답함"  # 같은 연결의 다음 키로 해결되면 대체 연결은 안 쓴다
    assert not any(c[0] == "anthropic" for c in world.calls)
    world.rules[("openai", "sk-oa-0002")] = fail(KIND_RATE_LIMIT)
    keypool.reset()
    res, _ = call(team)
    assert res.model == "claude-sonnet-5-5"


def test_disabled_fallback_and_missing_links_behave_like_before(
    client: TestClient, team: Team, world: World
) -> None:
    _a, b = _chain(client, team)
    put_fallback(client, team, [(b, "")], enabled=False)
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_OUTAGE)
    with pytest.raises(LlmError):
        call(team)
    with SessionLocal() as db:  # 자동 전환이 꺼져 있으면 예전처럼 어댑터를 바로 쓴다
        assert not isinstance(resolve_llm(db, team.ws, "default").adapter, ChainAdapter)


def test_capability_filter_json_and_vision(client: TestClient, team: Team, world: World) -> None:
    conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-oa-0001", default=True)
    b = conn(client, team, "perplexity", "검색형", "sonar", "pplx-0002")
    c = conn(client, team, "deepseek", "딥시크", "deepseek-chat", "ds-0003")
    d = conn(client, team, "anthropic", "클로드", "claude-sonnet-5-5", "sk-ant-0004")
    put_fallback(client, team, [(b, ""), (c, ""), (d, "")])
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_OUTAGE)
    # 평범한 호출: 첫 대체 연결이 답한다
    res, adapter = call(team)
    assert res.text == "좋아요" and adapter.answered_by.label == "검색형"
    # JSON 출력이 필요하면 JSON을 못 하는 연결(Sonar)은 건너뛴다
    res, adapter = call(team, json_schema={"type": "object"})
    assert adapter.answered_by.label == "딥시크"
    assert [t["status"] for t in adapter.trail] == ["failed", "skipped", "answered"]
    # 이미지가 있으면 이미지를 못 보는 연결을 모두 건너뛰고 Claude가 답한다
    res, adapter = call(team, images=[b"fake-image"])
    assert adapter.answered_by.label == "클로드" and res.model == "claude-sonnet-5-5"
    assert [t["status"] for t in adapter.trail] == ["failed", "skipped", "skipped", "answered"]


def test_tools_need_tool_capable_fallback_and_native_is_stripped(
    client: TestClient, team: Team, world: World
) -> None:
    conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-oa-0001", default=True)
    g = conn(client, team, "google", "구글", "gemini-2.5-flash", "g-0002")
    d = conn(client, team, "anthropic", "클로드", "claude-sonnet-5-5", "sk-ant-0003")
    put_fallback(client, team, [(g, ""), (d, "")])
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_OUTAGE)
    tools = [ToolDef("t", "도구", {"type": "object"})]
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "응", "native": ["공급자 원본"]},
        {"role": "user", "content": "다음"},
    ]
    with SessionLocal() as db:
        llm = resolve_llm(db, team.ws, "default")
        turn = llm.adapter.chat(model=llm.model, system="s", messages=msgs, tools=tools)
    assert turn.model == "claude-sonnet-5-5"  # 도구를 못 쓰는 구글 연결은 건너뜀
    sent = [m for p, m in world.chat_messages]
    assert any("native" in x for x in sent[0])  # 첫 연결에는 원본 그대로
    assert not any("native" in x for x in sent[-1])  # 다른 공급자에게는 원본을 빼고 보냄


def test_no_fallback_after_text_started_streaming(
    client: TestClient, team: Team, world: World
) -> None:
    _chain(client, team)
    world.rules[("openai", "sk-oa-0001")] = stream_then_fail(KIND_OUTAGE)
    got: list[str] = []
    with pytest.raises(LlmError):
        call(team, on_delta=got.append)
    assert got == ["안녕"] and not any(c[0] == "anthropic" for c in world.calls)


def test_fallback_settings_validation(client: TestClient, team: Team, world: World) -> None:
    a = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-oa-0001", default=True)
    b = conn(client, team, "anthropic", "대체", "claude-sonnet-5-5", "sk-ant-0002")
    rr = conn(client, team, "cohere-rerank", "재정렬", "rerank-v3.5", "co-key-0003")
    url = f"/api/v1/workspaces/{team.ws}/llm-fallback"
    h = team.h("owner")
    r = client.put(url, json={"enabled": True, "links": []}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["hint"]
    for bad in ("nope", rr):  # 없는 연결, 재정렬 전용 연결
        r = client.put(url, json={"enabled": True, "links": [{"provider_id": bad}]}, headers=h)
        assert r.status_code == 422, bad
    dup = client.put(
        url,
        json={"enabled": True, "links": [{"provider_id": b}, {"provider_id": b, "model": "x"}]},
        headers=h,
    )
    assert dup.status_code == 200 and len(dup.json()["links"]) == 1
    view = client.get(url, headers=h).json()
    assert view["enabled"] is True and view["triggers"] == DEFAULT_TRIGGERS
    assert {c["id"] for c in view["connections"]} == {a, b}  # 재정렬 전용은 목록에 없다
    assert view["links"][0]["label"] == "대체"


def test_dry_run_fallback_test(client: TestClient, team: Team, world: World) -> None:
    base = f"/api/v1/workspaces/{team.ws}/llm-fallback/test"
    h = team.h("owner")
    conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-oa-0001", default=True)
    r = client.post(base, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["hint"]  # 순서가 아직 없다
    _a, b = _chain(client, team)
    r = client.post(base, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["answered_by"]["label"] == "대체 Claude"
    assert [t["status"] for t in body["trail"]] == ["failed", "answered"]
    assert body["simulated"] == "outage"
    assert not any(c[0] == "openai" for c in world.calls)  # 첫 연결은 실제로 부르지 않았다
    put_fallback(client, team, [(b, "")], triggers={k: False for k in DEFAULT_TRIGGERS})
    r = client.post(base, headers=h)
    assert r.status_code == 422 and "조건" in r.json()["detail"]["message"]


def test_run_records_model_used_notes_and_cost_under_answering_model(
    client: TestClient, team: Team, world: World
) -> None:
    a = conn(client, team, "openai", "메인 GPT", "gpt-4o-mini", "sk-oa-0001", default=True)
    add_key(client, team, a, "sk-oa-0002")
    b = conn(client, team, "anthropic", "대체 Claude", "claude-sonnet-5-5", "sk-ant-0003")
    put_fallback(client, team, [(b, "")])
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_RATE_LIMIT)
    world.rules[("openai", "sk-oa-0002")] = fail(KIND_OUTAGE)
    world.rules[("anthropic", "sk-ant-0003")] = ok("대체가 답했어요", tokens=(1000, 500))
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {"id": "n2", "type": "llm", "data": {"prompt": "{{n1.message}}"}},
            {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}|{{n2.model_used}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    app_id = make_app(client, team, graph)
    d = start(client, team, app_id, {"message": "안녕"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "대체가 답했어요|claude-sonnet-5-5"
    step = next(s for s in d["steps"] if s["node_id"] == "n2")
    logs = step["logs"]
    assert "키 1번을 쓸 수 없어 키 2번으로 바꿔 다시 시도했어요." in logs
    assert "대체 연결(대체 Claude)로 답했어요." in logs
    assert step["output"]["model_used"] == "claude-sonnet-5-5"
    with SessionLocal() as db:
        run = db.get(Run, d["id"])
        assert run is not None
        assert float(run.cost) == pytest.approx(float(cost_of("claude-sonnet-5-5", 1000, 500)))
        assert float(run.cost) > 0


def test_app_override_off_and_custom(client: TestClient, team: Team, world: World) -> None:
    _a, b = _chain(client, team)
    world.rules[("openai", "sk-oa-0001")] = fail(KIND_OUTAGE)
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {"id": "n2", "type": "llm", "data": {"prompt": "{{n1.message}}"}},
            {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    app_id = make_app(client, team, graph)

    def features(fb: dict[str, Any]) -> None:
        r = client.patch(
            f"/api/v1/apps/{app_id}/features", json={"llm_fallback": fb}, headers=team.h("builder")
        )
        assert r.status_code == 200, r.text

    assert (
        start(client, team, app_id, {"message": "x"})["status"] == "succeeded"
    )  # 워크스페이스 설정대로
    features({"mode": "off"})
    d = start(client, team, app_id, {"message": "x"})
    assert d["status"] == "failed"  # 이 앱은 자동 전환을 쓰지 않는다
    # 이 앱만의 순서(워크스페이스 설정이 꺼져 있어도 동작)
    put_fallback(client, team, [(b, "")], enabled=False)
    features({"mode": "custom", "links": [{"provider_id": b, "model": ""}]})
    assert start(client, team, app_id, {"message": "x"})["status"] == "succeeded"


def test_app_override_sanitized_and_defaults_in_sync(client: TestClient, team: Team) -> None:
    assert DEFAULT_FEATURES["llm_fallback"]["triggers"] == DEFAULT_TRIGGERS
    app_id = make_app(client, team, {"nodes": [], "edges": []}, name="설정")
    links = [{"provider_id": f"id{i}", "model": " m "} for i in range(8)] + [{"provider_id": "id0"}]
    r = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={
            "llm_fallback": {"mode": "이상한값", "links": links, "triggers": {"auth": 1, "x": True}}
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    fb = r.json()["features"]["llm_fallback"]
    assert fb["mode"] == "inherit" and len(fb["links"]) == 5 and fb["links"][0]["model"] == "m"
    assert fb["triggers"]["auth"] is True and "x" not in fb["triggers"]


# ---------------------------------------------------------------- 오류 종류 분류
def _oa_exc(
    cls: type[openai.APIStatusError], status: int, body: dict[str, Any] | None = None
) -> Any:
    req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("x", response=httpx2.Response(status, request=req), body=body)


def test_openai_error_kinds() -> None:
    from api.llm.openai_adapter import _map_error

    assert _map_error(_oa_exc(openai.AuthenticationError, 401)).kind == KIND_AUTH
    assert _map_error(_oa_exc(openai.RateLimitError, 429)).kind == KIND_RATE_LIMIT
    assert _map_error(_oa_exc(openai.InternalServerError, 503)).kind == KIND_OUTAGE
    ctx = _oa_exc(
        openai.BadRequestError, 400, {"code": "context_length_exceeded", "message": "too long"}
    )
    assert _map_error(ctx).kind == KIND_CONTEXT
    filt = _oa_exc(openai.BadRequestError, 400, {"code": "content_filter", "message": "blocked"})
    assert _map_error(filt).kind == KIND_CONTENT_FILTER
    assert _map_error(_oa_exc(openai.BadRequestError, 400, {"message": "bad"})).kind == KIND_OTHER
    conn_err = openai.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    assert _map_error(conn_err).kind == KIND_OUTAGE


def test_google_error_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.llm.google_adapter import GoogleAdapter

    for status, kind in ((401, KIND_AUTH), (429, KIND_RATE_LIMIT), (503, KIND_OUTAGE)):
        monkeypatch.setattr(
            httpx,
            "post",
            lambda *a, _s=status, **k: httpx.Response(
                _s, request=httpx.Request("POST", "https://g")
            ),
        )
        with pytest.raises(LlmError) as exc:
            GoogleAdapter("k").complete(
                model="gemini-2.5-flash", system="", prompt="p", temperature=None, json_schema=None
            )
        assert exc.value.kind == kind


# ---------------------------------------------------------------- C. 재정렬 전용 모델
class Http:
    def __init__(
        self, payload: Any = None, status: int = 200, exc: Exception | None = None
    ) -> None:
        self.payload, self.status, self.exc = payload, status, exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers, "body": body})
        if self.exc is not None:
            raise self.exc
        req = httpx.Request("POST", url)
        if isinstance(self.payload, str):
            return httpx.Response(self.status, text=self.payload, request=req)
        return httpx.Response(self.status, json=self.payload, request=req)


DOCS = ["첫째 문서", "둘째 문서", "셋째 문서"]
RESULTS = {"results": [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}


@pytest.mark.parametrize(
    ("provider", "base", "url", "limit_key", "payload"),
    [
        ("cohere-rerank", None, "https://api.cohere.com/v2/rerank", "top_n", RESULTS),
        ("jina-rerank", None, "https://api.jina.ai/v1/rerank", "top_n", RESULTS),
        (
            "voyage-rerank",
            None,
            "https://api.voyageai.com/v1/rerank",
            "top_k",
            {"data": RESULTS["results"]},
        ),
        ("rerank-compatible", "http://vllm:8000", "http://vllm:8000/rerank", "top_n", RESULTS),
        (
            "rerank-compatible",
            "http://vllm:8000/v1",
            "http://vllm:8000/v1/rerank",
            "top_n",
            RESULTS,
        ),
        (
            "rerank-compatible",
            "http://tei:80/rerank",
            "http://tei:80/rerank",
            "top_n",
            {"results": [{"index": 2, "score": 0.9}, {"index": 0, "score": 0.2}]},
        ),
    ],
)
def test_rerank_adapters_request_shapes(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    base: str | None,
    url: str,
    limit_key: str,
    payload: Any,
) -> None:
    http = Http(payload)
    monkeypatch.setattr(rerank, "_http_post", http)
    out = rerank.call(provider, "secret-key-1234", base, "m-1", "질문", DOCS, 2)
    c = http.calls[0]
    assert c["url"] == url
    assert c["headers"]["Authorization"] == "Bearer secret-key-1234"
    assert c["body"]["model"] == "m-1" and c["body"]["query"] == "질문"
    assert c["body"]["documents"] == DOCS and c["body"][limit_key] == 2
    assert ("top_k" in c["body"]) == (limit_key == "top_k")
    assert [(r.index, r.score) for r in out] == [(2, 0.9), (0, 0.2)]  # 점수 높은 순


def test_rerank_clips_documents_and_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    http = Http({"results": [{"index": 0, "relevance_score": 0.5}]})
    monkeypatch.setattr(rerank, "_http_post", http)
    docs = ["가" * 5000] + ["나"] * 150
    rerank.call("cohere-rerank", "k-12345", None, "m", "q", docs, 999)
    body = http.calls[0]["body"]
    assert (
        len(body["documents"]) == rerank.MAX_DOCS
        and len(body["documents"][0]) == rerank.MAX_DOC_CHARS
    )
    assert body["top_n"] == len(docs)  # 문서 수보다 크게 보내지 않는다


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, KIND_AUTH),
        (403, KIND_AUTH),
        (429, KIND_RATE_LIMIT),
        (500, KIND_OUTAGE),
        (404, KIND_OTHER),
        (400, KIND_OTHER),
    ],
)
def test_rerank_errors_are_two_lines_without_secrets(
    monkeypatch: pytest.MonkeyPatch, status: int, kind: str
) -> None:
    monkeypatch.setattr(rerank, "_http_post", Http({"message": "secret-key-1234 invalid"}, status))
    with pytest.raises(LlmError) as exc:
        rerank.call("cohere-rerank", "secret-key-1234", None, "m", "q", DOCS)
    e = exc.value
    assert e.kind == kind and e.message and e.hint
    assert "secret-key-1234" not in e.message + e.hint


@pytest.mark.parametrize(
    "http",
    [
        Http("<html>not json</html>"),
        Http({"results": []}),
        Http({"results": [{"index": 99, "relevance_score": 1}]}),
        Http({"unexpected": True}),
        Http(exc=httpx.ReadTimeout("느려요")),
        Http(exc=httpx.ConnectError("끊김")),
    ],
)
def test_rerank_bad_responses(monkeypatch: pytest.MonkeyPatch, http: Http) -> None:
    monkeypatch.setattr(rerank, "_http_post", http)
    with pytest.raises(LlmError) as exc:
        rerank.call("jina-rerank", "k-12345", None, "m", "q", DOCS)
    assert exc.value.message and exc.value.hint


def test_rerank_documents_rotates_keys(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = conn(client, team, "cohere-rerank", "코히어", "rerank-v3.5", "co-first-0001")
    add_key(client, team, cid, "co-second-0002")
    seen: list[str] = []

    def post(url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        seen.append(headers["Authorization"])
        req = httpx.Request("POST", url)
        if len(seen) == 1:
            return httpx.Response(429, json={}, request=req)
        return httpx.Response(200, json=RESULTS, request=req)

    monkeypatch.setattr(rerank, "_http_post", post)
    with SessionLocal() as db:
        row = db.get(LlmProvider, cid)
        assert row is not None
        out = rerank.rerank_documents(row, "", "질문", DOCS)
    assert seen == ["Bearer co-first-0001", "Bearer co-second-0002"] and out[0].index == 2
    assert keypool.cooldown_left(cid, "primary") > 0


def test_rerank_connections_stay_out_of_chat(client: TestClient, team: Team, world: World) -> None:
    chat = conn(client, team, "openai", "메인", "gpt-4o-mini", "sk-oa-0001", default=True)
    rr = conn(
        client, team, "jina-rerank", "재정렬", "jina-reranker-v2-base-multilingual", "jina-0002"
    )
    rows = client.get(f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("owner")).json()
    by = {r["id"]: r for r in rows}
    assert (
        by[chat]["is_default"] is True
        and by[rr]["is_default"] is False
        and by[rr]["rerank"] is True
    )
    with SessionLocal() as db:
        assert resolve_llm(db, team.ws, "default").provider.id == chat
        with pytest.raises(LlmError):
            resolve_llm(db, team.ws, rr)  # 재정렬 전용 연결은 대화 연결로 못 고른다
    # 대화 연결을 지워도 재정렬 연결이 기본 연결이 되지는 않는다
    client.delete(f"/api/v1/workspaces/{team.ws}/llm-providers/{chat}", headers=team.h("owner"))
    with SessionLocal() as db, pytest.raises(LlmError):
        resolve_llm(db, team.ws, "default")
    listing = client.get(
        f"/api/v1/workspaces/{team.ws}/rerank-connections", headers=team.h("builder")
    ).json()
    assert [r["id"] for r in listing] == [rr] and "key" not in str(listing)


def test_rerank_presets_listed_but_not_in_chat_catalog(client: TestClient, team: Team) -> None:
    provs = client.get("/api/v1/llm/providers", headers=team.h("member")).json()
    rr = [p for p in provs if p["rerank"]]
    assert {p["key"] for p in rr} == {
        "cohere-rerank",
        "jina-rerank",
        "voyage-rerank",
        "rerank-compatible",
    }
    assert all(p["group"] == "재정렬 전용" for p in rr)
    catalog = client.get("/api/v1/llm/catalog", headers=team.h("member")).json()
    assert not any(m["provider"] in {p["key"] for p in rr} for m in catalog)
    with pytest.raises(LlmError):
        llm_registry.default_factory("cohere-rerank", "k", None)


def test_rerank_compatible_needs_address(client: TestClient, team: Team) -> None:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "rerank-compatible",
            "label": "사내",
            "api_key": "k-12345",
            "default_model": "bge",
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 422 and r.json()["detail"]["hint"]


def test_rerank_connection_test(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rerank, "_http_post", Http(RESULTS))
    url = f"/api/v1/workspaces/{team.ws}/llm-providers/test"
    r = client.post(
        url,
        json={"provider": "voyage-rerank", "api_key": "vo-key-0001", "model": "rerank-2.5"},
        headers=team.h("owner"),
    )
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["models"] == []
    monkeypatch.setattr(rerank, "_http_post", Http({}, 401))
    r = client.post(
        url, json={"provider": "voyage-rerank", "api_key": "vo-key-0001"}, headers=team.h("owner")
    )
    assert r.json()["ok"] is False and r.json()["hint"] and "vo-key-0001" not in r.text


def _kb_with_docs(client: TestClient, team: Team) -> str:
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "규정"},
        headers=team.h("builder"),
    ).json()["id"]
    for name, body in (
        ("규정1.txt", "연차 휴가 규정 첫 번째 안내"),
        ("규정2.txt", "연차 휴가 규정 두 번째 안내"),
    ):
        res = client.post(
            f"/api/v1/knowledge-bases/{kb}/documents",
            files={"file": (name, io.BytesIO(body.encode()), "text/plain")},
            headers=team.h("builder"),
        )
        assert res.status_code == 200, res.text
    return str(kb)


def test_knowledge_search_uses_dedicated_rerank_and_falls_back(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    rr = conn(client, team, "cohere-rerank", "코히어", "rerank-v3.5", "co-key-0001")
    kb = _kb_with_docs(client, team)

    def search() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = client.post(
            f"/api/v1/knowledge-bases/{kb}/search",
            json={"query": "연차 휴가 규정", "method": "keyword", "top_k": 5},
            headers=team.h("builder"),
        ).json()
        return out

    plain = search()
    assert len(plain) == 2 and "rerank_score" not in plain[0]
    # 설정: 재정렬을 켜고 전용 모델을 고른다
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb}",
        json={
            "settings": {
                "retrieval": {
                    "rerank": True,
                    "rerank_connection": rr,
                    "rerank_model": "rerank-v3.5",
                }
            }
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    # 전용 모델이 두 번째 조각을 1등으로 올린다
    http = Http(
        {"results": [{"index": 1, "relevance_score": 0.99}, {"index": 0, "relevance_score": 0.01}]}
    )
    monkeypatch.setattr(rerank, "_http_post", http)
    got = search()
    assert got[0]["chunk_id"] == plain[1]["chunk_id"] and got[0]["rerank_score"] == 0.99
    assert (
        http.calls[0]["body"]["model"] == "rerank-v3.5"
        and len(http.calls[0]["body"]["documents"]) == 2
    )
    # 전용 모델이 실패하면 AI(LLM) 재정렬로 이어 가고, 검색은 깨지지 않는다
    monkeypatch.setattr(rerank, "_http_post", Http({}, 500))
    after = search()
    assert len(after) == 2 and "rerank_score" not in after[0]


def test_kb_settings_reject_bad_rerank_connection(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    chat = add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "x"},
        headers=team.h("builder"),
    ).json()["id"]
    for bad in (chat["id"], "no-such-id"):
        r = client.patch(
            f"/api/v1/knowledge-bases/{kb}",
            json={"settings": {"retrieval": {"rerank": True, "rerank_connection": bad}}},
            headers=team.h("builder"),
        )
        assert r.status_code == 422 and r.json()["detail"]["hint"], bad
    ok_r = client.patch(
        f"/api/v1/knowledge-bases/{kb}",
        json={"settings": {"retrieval": {"rerank_connection": ""}}},
        headers=team.h("builder"),
    )
    assert ok_r.status_code == 200
