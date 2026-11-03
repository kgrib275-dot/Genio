"""LLM 어댑터 공통 인터페이스.

대화 메시지는 공급자에 상관없는 형식을 쓴다:
- {"role": "user", "content": str}
- {"role": "assistant", "content": str, "tool_calls": [ToolCall], "native": 공급자 원본}
- {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from nodes import LlmResult


class LlmError(Exception):
    """사용자에게 보여도 되는 한국어 오류. 공급자 원문·키는 담지 않는다."""

    def __init__(self, message: str, hint: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.retryable = retryable


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    # 입력 JSON을 읽지 못했거나 잘렸을 때의 원문
    invalid_input: str | None = None


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ChatTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    native: Any = None


Message = dict[str, Any]
OnText = Callable[[str], None]


class ChatAdapter(Protocol):
    provider: str

    def complete(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
        on_delta: OnText | None = None,
    ) -> LlmResult: ...

    # on_delta: 답이 만들어지는 대로 글 조각을 받는다(v0.4 답변 실시간 표시).

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn: ...

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...


def json_instruction(schema: dict[str, Any]) -> str:
    return (
        "\n\n반드시 아래 JSON Schema에 맞는 JSON 객체 하나만 답하세요. 설명이나 코드 단계 표시는 쓰지 마세요.\n"
        + json.dumps(schema, ensure_ascii=False)
    )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any] | None:
    candidates = [text.strip()]
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None
