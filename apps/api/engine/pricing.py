"""모델 단가표(USD / 1M 토큰). 설계서 §5: 토큰 수 × 단가로 run.cost 계산.

단가는 참고용이다. 바뀌면 이 표만 고친다. 표에 없는 모델은 0으로 계산한다.
"""

from decimal import Decimal

PRICES: dict[str, tuple[str, str]] = {
    # model: (input, output)
    "claude-fable-5-1": ("10", "50"),
    "claude-opus-5-5": ("4", "20"),
    "claude-opus-5": ("5", "25"),
    "claude-sonnet-5-5": ("2", "10"),
    "claude-sonnet-5": ("2", "10"),
    "claude-haiku-5-5": ("0.10", "0.50"),
    "claude-haiku-4-5": ("1", "5"),
    "gpt-4o": ("2.50", "10"),
    "gpt-4o-mini": ("0.15", "0.60"),
    "gpt-4.1": ("2", "8"),
    "gpt-4.1-mini": ("0.40", "1.60"),
    "text-embedding-3-small": ("0.02", "0"),
    "text-embedding-3-large": ("0.13", "0"),
    "gemini-2.0-flash": ("0.10", "0.40"),
}

MILLION = Decimal(1_000_000)


def cost_of(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price = PRICES.get(model)
    if price is None:
        # 날짜가 붙은 이름(gpt-4o-mini-2024-07-18 등)은 앞부분으로 찾는다
        price = next((p for m, p in PRICES.items() if model.startswith(m + "-")), None)
    if price is None:
        return Decimal("0")
    return (Decimal(price[0]) * input_tokens + Decimal(price[1]) * output_tokens) / MILLION
