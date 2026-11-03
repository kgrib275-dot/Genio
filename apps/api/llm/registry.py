"""워크스페이스에 등록된 LLM 연결(llm_providers)에서 어댑터를 만든다."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.crypto import decrypt_str
from api.llm.anthropic_adapter import AnthropicAdapter
from api.llm.base import ChatAdapter, LlmError
from api.llm.google_adapter import GoogleAdapter
from api.llm.openai_adapter import OpenAIAdapter
from api.models import LlmProvider

PROVIDERS = ("openai", "anthropic", "google", "openai-compatible")


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
    if provider in ("openai", "openai-compatible"):
        return OpenAIAdapter(api_key, base_url, provider=provider)
    raise LlmError(
        f"'{provider}' 공급자는 지원하지 않아요.",
        "openai, anthropic, google, openai-compatible 중에서 고르세요.",
    )


# 테스트에서 가짜 어댑터로 바꿀 수 있게 모듈 변수로 둔다
adapter_factory: AdapterFactory = default_factory


def _no_provider() -> LlmError:
    return LlmError(
        "등록된 AI 연결이 없어요.",
        "워크스페이스 설정 > AI 연결에서 API 키를 등록하세요.",
    )


def resolve_llm(
    db: Session,
    workspace_id: str,
    ref: str = "default",
    model: str | None = None,
    *,
    purpose: str = "chat",
) -> ResolvedLlm:
    """ref: "default" | 연결 id | 공급자 이름 | 연결 이름."""
    rows = list(db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == workspace_id)))
    if not rows:
        raise _no_provider()
    chosen: LlmProvider | None = None
    if purpose == "embedding":
        chosen = next(
            (r for r in rows if r.provider in ("openai", "openai-compatible") and r.is_default),
            None,
        )
        chosen = chosen or next(
            (r for r in rows if r.provider in ("openai", "openai-compatible")), None
        )
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
                "노드 설정에서 AI 연결을 '기본'으로 바꾸거나 다시 고르세요.",
            )
    secret = decrypt_str(chosen.api_key_encrypted)
    adapter = adapter_factory(chosen.provider, secret, chosen.base_url)
    return ResolvedLlm(
        adapter=adapter, model=model or chosen.default_model, provider=chosen, secret=secret
    )
