"""키 돌려쓰기 + 공급자 자동 전환(v0.9, ADR 0013).

ChainAdapter는 어댑터처럼 보이지만 안에서 이렇게 움직인다.
1) 연결(hop)마다 키를 순서대로 써 본다. 한도·키 오류면 그 키를 쉬게 하고 다음 키로 넘어간다.
2) 그 연결의 키를 모두 써도 안 되면, 오류 종류가 '자동 전환 조건'에 맞을 때 다음 연결(대체 연결)로 넘어간다.
   JSON 출력·이미지·도구 호출이 필요한 호출은 그것을 지원하는 연결로만 넘어간다.
3) 어떻게 넘어갔는지는 notes에 한국어 문장으로 남겨 실행 기록에 보여 준다.
이미 답의 글자를 흘려보낸 뒤에는 이어붙일 수 없어서 넘어가지 않고 오류를 그대로 낸다.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from api.llm import keypool
from api.llm.base import (
    KIND_AUTH,
    KIND_CONTENT_FILTER,
    KIND_CONTEXT,
    KIND_OUTAGE,
    KIND_RATE_LIMIT,
    ChatAdapter,
    ChatTurn,
    LlmError,
    Message,
    OnText,
    ToolDef,
)
from api.llm.presets import (
    model_supports_json,
    model_supports_vision,
    provider_supports_tools,
)
from nodes import LlmResult

log = logging.getLogger("genio.llm.chain")
T = TypeVar("T")

MAX_KEY_ATTEMPTS = 5
MAX_LINKS = 5
DEFAULT_TRIGGERS: dict[str, bool] = {
    "outage": True,  # 연결 실패·시간 초과·서버 오류
    "rate_limit": True,  # 한도 초과(키를 모두 써 본 뒤)
    "content_filter": False,  # 안전 정책으로 답하지 않음(선택)
    "context_length": False,  # 입력이 너무 김(선택)
    "auth": False,  # 키 오류(선택)
}
_KIND_TO_TRIGGER = {
    KIND_OUTAGE: "outage",
    KIND_RATE_LIMIT: "rate_limit",
    KIND_CONTENT_FILTER: "content_filter",
    KIND_CONTEXT: "context_length",
    KIND_AUTH: "auth",
}

AdapterFactory = Callable[[str, str, str | None], ChatAdapter]


def merge_triggers(raw: Any) -> dict[str, bool]:
    out = dict(DEFAULT_TRIGGERS)
    if isinstance(raw, dict):
        for k in out:
            if k in raw:
                out[k] = bool(raw[k])
    return out


def effective_fallback(workspace_cfg: Any, app_override: Any = None) -> dict[str, Any] | None:
    """워크스페이스 설정과 앱 설정(inherit | off | custom)을 합쳐 지금 쓸 자동 전환 설정."""
    mode = (
        str((app_override or {}).get("mode") or "inherit")
        if isinstance(app_override, dict)
        else "inherit"
    )
    if mode == "off":
        return None
    if mode == "custom" and isinstance(app_override, dict):
        cfg: dict[str, Any] = {"enabled": True, **app_override}
    else:
        cfg = workspace_cfg if isinstance(workspace_cfg, dict) else {}
    links = cfg.get("links")
    if not cfg.get("enabled") or not isinstance(links, list) or not links:
        return None
    return {"links": links[:MAX_LINKS], "triggers": merge_triggers(cfg.get("triggers"))}


@dataclass
class Hop:
    conn_id: str
    provider: str
    label: str
    base_url: str | None
    model: str
    keys: list[keypool.KeyRef]
    strategy: str = "failover"


@dataclass
class ChainAdapter:
    """ChatAdapter처럼 쓰는 키 돌려쓰기·자동 전환 묶음."""

    hops: list[Hop]
    factory: AdapterFactory
    triggers: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_TRIGGERS))
    # 시험용: 첫 연결이 이 종류의 오류로 실패한 것처럼 만든다(실제로 부르지 않는다)
    simulate_first_failure: str | None = None
    provider: str = "chain"
    notes: list[str] = field(default_factory=list)
    trail: list[dict[str, Any]] = field(default_factory=list)
    answered_by: Hop | None = None

    # ---- 공통 ----
    def take_notes(self) -> list[str]:
        out, self.notes = self.notes, []
        return out

    def _eligible(self, hop: Hop, *, json: bool, vision: bool, tools: bool) -> bool:
        if json and not model_supports_json(hop.provider, hop.model):
            return False
        if vision:
            v = model_supports_vision(hop.provider, hop.model)
            if v is not True and not (v is None and hop.provider in ("azure", "openai-compatible")):
                return False
        return not (tools and not provider_supports_tools(hop.provider, hop.model))

    def _wants_fallback(self, exc: LlmError) -> bool:
        name = _KIND_TO_TRIGGER.get(exc.kind)
        return bool(name and self.triggers.get(name))

    def _run_hop(
        self,
        hop: Hop,
        model: str,
        op: Callable[[ChatAdapter, str], T],
        emitted: Callable[[], bool],
    ) -> T:
        keys = keypool.order(hop.conn_id, hop.keys, hop.strategy)
        if not keys:
            raise LlmError(
                "사용할 수 있는 키가 없어요.",
                "관리 > AI 모델에서 키를 켜거나 새로 추가하세요.",
                kind=KIND_AUTH,
            )
        attempts = keys[:MAX_KEY_ATTEMPTS]
        last: LlmError | None = None
        for n, key in enumerate(attempts):
            adapter = self.factory(hop.provider, key.secret, hop.base_url)
            try:
                out = op(adapter, model)
            except LlmError as exc:
                keypool.record(hop.conn_id, key.id, ok=False, error=exc.message)
                last = exc
                if exc.kind == KIND_RATE_LIMIT:
                    keypool.set_cooldown(hop.conn_id, key.id, keypool.COOLDOWN_RATE_LIMIT)
                elif exc.kind == KIND_AUTH:
                    keypool.set_cooldown(hop.conn_id, key.id, keypool.COOLDOWN_AUTH)
                else:
                    raise  # 연결·서버 문제나 요청 오류는 키가 원인이 아니라서 키를 바꿔도 소용없다
                if emitted() or n + 1 >= len(attempts):
                    raise
                nxt = attempts[n + 1]
                self.notes.append(
                    f"키 {key.position}번을 쓸 수 없어 키 {nxt.position}번으로 바꿔 다시 시도했어요."
                )
                continue
            keypool.record(hop.conn_id, key.id, ok=True)
            return out
        raise last or LlmError("AI 호출에 실패했어요.", "잠시 후 다시 시도하세요.")

    def _run(
        self,
        op: Callable[[ChatAdapter, str, bool], T],
        *,
        first_model: str,
        json: bool = False,
        vision: bool = False,
        tools: bool = False,
        emitted: Callable[[], bool] = lambda: False,
        fallback: bool = True,
    ) -> T:
        last: LlmError | None = None
        order = list(range(len(self.hops)))
        for pos, i in enumerate(order):
            hop = self.hops[i]
            if i > 0 and not self._eligible(hop, json=json, vision=vision, tools=tools):
                self.trail.append(
                    {"label": hop.label, "model": hop.model, "status": "skipped", "error": ""}
                )
                continue
            model = first_model if i == 0 else hop.model
            try:
                if i == 0 and self.simulate_first_failure:
                    raise LlmError(
                        "연습: 첫 연결이 실패한 것처럼 만들었어요.",
                        "실제 호출은 하지 않았어요.",
                        retryable=True,
                        kind=self.simulate_first_failure,
                    )
                switched = i > 0

                def hop_op(a: ChatAdapter, m: str, sw: bool = switched) -> T:
                    return op(a, m, sw)

                out = self._run_hop(hop, model, hop_op, emitted)
            except LlmError as exc:
                last = exc
                self.trail.append(
                    {"label": hop.label, "model": model, "status": "failed", "error": exc.message}
                )
                rest = [
                    j
                    for j in order[pos + 1 :]
                    if self._eligible(self.hops[j], json=json, vision=vision, tools=tools)
                ]
                if emitted() or not fallback or not rest or not self._wants_fallback(exc):
                    raise
                nxt = self.hops[rest[0]]
                self.notes.append(
                    f"{hop.label} 연결이 되지 않아 {nxt.label} 연결로 넘어가요({exc.message})"
                )
                continue
            self.trail.append(
                {"label": hop.label, "model": model, "status": "answered", "error": ""}
            )
            self.answered_by = hop
            if i > 0:
                self.notes.append(f"대체 연결({hop.label})로 답했어요.")
            return out
        raise last or LlmError("AI 호출에 실패했어요.", "잠시 후 다시 시도하세요.")

    # ---- ChatAdapter ----
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
        sent = [0]

        def wrapped(text: str) -> None:
            sent[0] += 1
            if on_delta is not None:
                on_delta(text)

        def op(adapter: ChatAdapter, use_model: str, switched: bool) -> LlmResult:
            kwargs: dict[str, Any] = {}
            if images:
                kwargs["images"] = images
            res = adapter.complete(
                model=use_model,
                system=system,
                prompt=prompt,
                temperature=temperature,
                json_schema=json_schema,
                on_delta=wrapped if on_delta is not None else None,
                **kwargs,
            )
            if not res.model:
                res.model = use_model
            return res

        return self._run(
            op,
            first_model=model,
            json=json_schema is not None,
            vision=bool(images),
            emitted=lambda: sent[0] > 0,
        )

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn:
        sent = [0]

        def wrapped(text: str) -> None:
            sent[0] += 1
            if on_text is not None:
                on_text(text)

        def op(adapter: ChatAdapter, use_model: str, switched: bool) -> ChatTurn:
            # 공급자 원본(native)은 그 공급자만 읽을 수 있어서, 다른 연결로 넘어가면 뺀다
            msgs = (
                [{k: v for k, v in m.items() if k != "native"} for m in messages]
                if switched
                else messages
            )
            turn = adapter.chat(
                model=use_model,
                system=system,
                messages=msgs,
                tools=tools,
                on_text=wrapped if on_text is not None else None,
            )
            if not turn.model:
                turn.model = use_model
            return turn

        return self._run(
            op,
            first_model=model,
            tools=bool(tools),
            emitted=lambda: sent[0] > 0,
        )

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        def op(adapter: ChatAdapter, use_model: str, switched: bool) -> list[list[float]]:
            return adapter.embed(model=use_model, texts=texts)

        # 임베딩은 연결마다 차원이 달라 다른 공급자로 넘어가지 않고 키만 돌려 쓴다
        return self._run(op, first_model=model, fallback=False)


def pop_notes(adapter: object) -> list[str]:
    """어댑터가 ChainAdapter면 쌓인 안내 문장을 꺼낸다(아니면 빈 목록)."""
    fn = getattr(adapter, "take_notes", None)
    return list(fn()) if callable(fn) else []
