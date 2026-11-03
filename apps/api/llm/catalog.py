"""모델 카탈로그(기능 정의서 §6): 모델별 컨텍스트·단가·기능.

단가는 engine/pricing.py의 표를 그대로 쓴다(한 곳에서 관리). 컨텍스트 크기는 참고값이다.
공급자가 바뀌면 이 표와 pricing.PRICES만 고친다.
"""

from decimal import Decimal
from typing import Any

from api.engine.pricing import PRICES

# (provider, model, 표시 이름, 컨텍스트, tools, vision, embedding, 차원)
_MODELS: list[tuple[str, str, str, int, bool, bool, bool, int | None]] = [
    (
        "anthropic",
        "claude-fable-5-1",
        "Claude Fable 5.1 (가장 똑똑함)",
        200_000,
        True,
        True,
        False,
        None,
    ),
    ("anthropic", "claude-opus-5-5", "Claude Opus 5.5", 200_000, True, True, False, None),
    (
        "anthropic",
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5 (기본 추천)",
        200_000,
        True,
        True,
        False,
        None,
    ),
    (
        "anthropic",
        "claude-haiku-5-5",
        "Claude Haiku 5.5 (빠르고 저렴)",
        200_000,
        True,
        True,
        False,
        None,
    ),
    ("openai", "gpt-4.1", "GPT-4.1", 1_000_000, True, True, False, None),
    ("openai", "gpt-4.1-mini", "GPT-4.1 mini", 1_000_000, True, True, False, None),
    ("openai", "gpt-4o", "GPT-4o", 128_000, True, True, False, None),
    ("openai", "gpt-4o-mini", "GPT-4o mini", 128_000, True, True, False, None),
    ("google", "gemini-2.0-flash", "Gemini 2.0 Flash", 1_000_000, True, True, False, None),
    (
        "openai",
        "text-embedding-3-small",
        "OpenAI 임베딩 small (기본)",
        8_191,
        False,
        False,
        True,
        1536,
    ),
    (
        "openai",
        "text-embedding-3-large",
        "OpenAI 임베딩 large (1536차원으로 줄여 씀)",
        8_191,
        False,
        False,
        True,
        1536,
    ),
    (
        "openai-compatible",
        "bge-m3",
        "BGE-M3 다국어 임베딩 (호환 API·사내 서버)",
        8_192,
        False,
        False,
        True,
        1024,
    ),
    (
        "openai-compatible",
        "multilingual-e5-large",
        "Multilingual E5 large (호환 API·사내 서버)",
        512,
        False,
        False,
        True,
        1024,
    ),
]


def _price(model: str) -> tuple[float, float]:
    p = PRICES.get(model)
    if p is None:
        return (0.0, 0.0)
    return (float(Decimal(p[0])), float(Decimal(p[1])))


def catalog() -> list[dict[str, Any]]:
    out = []
    for provider, model, label, ctx, tools, vision, emb, dims in _MODELS:
        inp, outp = _price(model)
        out.append(
            {
                "provider": provider,
                "model": model,
                "label": label,
                "context_window": ctx,
                "input_price": inp,  # USD / 100만 토큰
                "output_price": outp,
                "tools": tools,
                "vision": vision,
                "embedding": emb,
                "dimensions": dims,
            }
        )
    return out


def embedding_models() -> list[str]:
    return [m for _, m, _, _, _, _, emb, _ in _MODELS if emb]


def is_known(model: str) -> bool:
    return any(m == model for _, m, *_ in _MODELS)
