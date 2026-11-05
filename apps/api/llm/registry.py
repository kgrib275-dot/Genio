"""워크스페이스에 등록된 LLM 연결(llm_providers)에서 어댑터를 만든다."""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.crypto import decrypt_str
from api.llm import keypool
from api.llm.anthropic_adapter import AnthropicAdapter
from api.llm.base import ChatAdapter, LlmError
from api.llm.chain import DEFAULT_TRIGGERS, ChainAdapter, Hop, effective_fallback
from api.llm.google_adapter import GoogleAdapter
from api.llm.openai_adapter import OpenAIAdapter
from api.llm.presets import COMPAT_KEYS, PRESETS, is_rerank, preset_base_url
from api.models import LlmProvider, Workspace

# 기본 5종 + OpenAI 호환 공급자 preset(v0.6, llm/presets.py)
PROVIDERS = tuple(PRESETS)
EMBEDDING_PROVIDERS = ("openai", "openai-compatible", "azure")


@dataclass
class ResolvedLlm:
    adapter: ChatAdapter
    model: str
    provider: LlmProvider
    secret: str


AdapterFactory = Callable[[str, str, str | None], ChatAdapter]


def default_factory(provider: str, api_key: str, base_url: str | None) -> ChatAdapter:
    if provider == "anthropic":
        return AnthropicAdapter(api_key, base_url)
    if provider == "google":
        return GoogleAdapter(api_key, base_url)
    if provider in ("openai", "openai-compatible", "azure"):
        return OpenAIAdapter(api_key, base_url, provider=provider)
    if provider in COMPAT_KEYS:
        # 미리 설정한 OpenAI 호환 공급자: 주소를 따로 넣지 않았으면 기본 주소를 쓴다
        return OpenAIAdapter(api_key, base_url or preset_base_url(provider), provider=provider)
    raise LlmError(
        f"'{provider}' 공급자는 지원하지 않아요.",
        "워크스페이스 설정 > AI 연결의 공급자 목록에서 다시 고르세요.",
    )


# 테스트에서 가짜 어댑터로 바꿀 수 있게 모듈 값으로 둔다
adapter_factory: AdapterFactory = default_factory


def _no_provider() -> LlmError:
    return LlmError(
        "등록된 AI 연결이 없어요.",
        "워크스페이스 설정 > AI 연결에서 API 키를 등록하세요.",
    )


def key_refs(row: LlmProvider) -> list[keypool.KeyRef]:
    """연결의 키 목록(기본 키 + 더 둔 키). 꺼 둔 키·읽을 수 없는 키는 뺀다. 번호는 화면 순서."""
    out: list[keypool.KeyRef] = []
    with contextlib.suppress(ValueError):
        out.append(
            keypool.KeyRef(
                "primary",
                "기본 키",
                decrypt_str(row.api_key_encrypted),
                int(row.primary_weight or 1),
                1,
            )
        )

    for pos, k in enumerate(row.extra_keys or [], start=2):
        if not isinstance(k, dict) or k.get("disabled"):
            continue
        try:
            secret = decrypt_str(str(k.get("key_encrypted") or "").encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            continue
        out.append(
            keypool.KeyRef(
                str(k.get("id")),
                str(k.get("label") or f"키 {pos}"),
                secret,
                int(k.get("weight") or 1),
                pos,
            )
        )
    return out


def hop_for(row: LlmProvider, model: str) -> Hop:
    return Hop(
        conn_id=row.id,
        provider=row.provider,
        label=row.label,
        base_url=row.base_url,
        model=model,
        keys=key_refs(row),
        strategy=row.key_strategy or "failover",
    )


def _factory(provider: str, key: str, base_url: str | None) -> ChatAdapter:
    # 시험에서 adapter_factory를 바꿔 끼우므로 부를 때 모듈 값을 읽는다
    return adapter_factory(provider, key, base_url)


def resolve_llm(
    db: Session,
    workspace_id: str,
    ref: str = "default",
    model: str | None = None,
    *,
    purpose: str = "chat",
    fallback: dict[str, Any] | None = None,
    simulate_first_failure: str | None = None,
) -> ResolvedLlm:
    """ref: "default" | 연결 id | 공급자 이름 | 연결 이름.

    fallback: 앱별 자동 전환 설정(features.llm_fallback). 없으면 워크스페이스 설정을 따른다.
    simulate_first_failure: 시험용. 첫 연결이 이 종류의 오류로 실패한 것처럼 만든다.
    """
    # 재정렬 전용 연결(v0.9)은 대화·임베딩 연결로 고르지 않는다
    rows = [
        r
        for r in db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == workspace_id))
        if not is_rerank(r.provider)
    ]
    if not rows:
        raise _no_provider()
    chosen: LlmProvider | None = None
    ws = db.get(Workspace, workspace_id)
    defaults = ((ws.settings or {}).get("default_models") or {}) if ws else {}
    by_id = {r.id: r for r in rows}
    if purpose == "embedding" and defaults.get("embedding") in by_id:
        chosen = by_id[defaults["embedding"]]
    elif purpose == "chat" and ref in ("", "default") and defaults.get("chat") in by_id:
        chosen = by_id[defaults["chat"]]
    if chosen is not None:
        pass
    elif purpose == "embedding":
        chosen = next(
            (r for r in rows if r.provider in EMBEDDING_PROVIDERS and r.is_default),
            None,
        )
        chosen = chosen or next((r for r in rows if r.provider in EMBEDDING_PROVIDERS), None)
        if chosen is None:
            raise LlmError(
                "문서 임베딩에 쓸 OpenAI 연결이 없어요.",
                "워크스페이스 설정 > AI 연결에 OpenAI 키를 등록하세요.",
            )
    elif ref in ("", "default"):
        chosen = next((r for r in rows if r.is_default), rows[0])
    else:
        chosen = next(
            (r for r in rows if ref in (r.id, r.label)),
            next((r for r in rows if r.provider == ref), None),
        )
        if chosen is None:
            raise LlmError(
                f"'{ref}' AI 연결을 찾지 못했어요.",
                "단계 설정에서 AI 연결을 '기본'으로 바꾸거나 다시 고르세요.",
            )
    secret = decrypt_str(chosen.api_key_encrypted)
    use_model = model or chosen.default_model
    hops = [hop_for(chosen, use_model)]
    triggers: dict[str, bool] | None = None
    if purpose == "chat":
        cfg = effective_fallback((ws.settings or {}).get("llm_fallback") if ws else None, fallback)
        if cfg is not None:
            triggers = cfg["triggers"]
            for link in cfg["links"]:
                if not isinstance(link, dict):
                    continue
                row = by_id.get(str(link.get("provider_id")))
                if row is None or any(h.conn_id == row.id for h in hops):
                    continue
                hops.append(hop_for(row, str(link.get("model") or row.default_model)))
    if len(hops) == 1 and len(hops[0].keys) <= 1 and not simulate_first_failure:
        # 키 하나·대체 연결 없음: 예전과 똑같이 어댑터를 바로 쓴다
        adapter = adapter_factory(chosen.provider, secret, chosen.base_url)
    else:
        adapter = ChainAdapter(
            hops,
            factory=_factory,
            triggers=triggers if triggers is not None else dict(DEFAULT_TRIGGERS),
            simulate_first_failure=simulate_first_failure,
        )
    return ResolvedLlm(adapter=adapter, model=use_model, provider=chosen, secret=secret)
