"""테스트용 가짜 LLM 어댑터. 실제 공급자를 부르지 않는다."""

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Any

from api.llm.base import ChatTurn, Message, OnText, ToolCall, ToolDef, parse_json_object
from nodes import LlmResult

DIM = 1536


def fake_embedding(text: str) -> list[float]:
    """단어 해시 기반 결정적 벡터. 같은 단어가 많을수록 코사인 유사도가 높다."""
    vec = [0.0] * DIM
    for word in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        for gram in {word, *(word[i : i + 2] for i in range(max(len(word) - 1, 0)))}:
            h = int(hashlib.md5(gram.encode()).hexdigest(), 16)  # noqa: S324 - 테스트용 해시
            vec[h % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def classify(text: str) -> str:
    if any(w in text for w in ("결제", "환불", "청구", "카드")):
        return "billing"
    if any(w in text for w in ("오류", "에러", "버그", "로그인", "접속")):
        return "tech"
    return "other"


class FakeAdapter:
    """complete: 규칙 기반 응답. chat: 스크립트(턴 함수 목록) 재생."""

    provider = "fake"

    def __init__(self, script: list[Callable[[list[Message]], ChatTurn]] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
        on_delta: OnText | None = None,
    ) -> LlmResult:
        self.calls.append({"kind": "complete", "system": system, "prompt": prompt})
        if json_schema:
            props = json_schema.get("properties", {})
            data: dict[str, Any] = {}
            for key, spec in props.items():
                if spec.get("enum"):
                    guess = classify(prompt)
                    data[key] = guess if guess in spec["enum"] else spec["enum"][0]
                elif key == "category":
                    data[key] = classify(prompt)
                elif spec.get("type") == "string":
                    data[key] = f"{key}: {prompt[:30]}"
                elif spec.get("type") == "array":
                    data[key] = [f"{key} 예시 {i}" for i in range(1, 4)]
                else:
                    data[key] = None
            text = json.dumps(data, ensure_ascii=False)
            return LlmResult(
                text=text,
                data=parse_json_object(text),
                model=model,
                input_tokens=100,
                output_tokens=20,
            )
        if "자료:" in prompt:
            ctx = prompt.split("자료:", 1)[1]
            first = ctx.strip().splitlines()[0] if ctx.strip() else ""
            return LlmResult(
                text=f"문서에 따르면: {first[:80]}", model=model, input_tokens=200, output_tokens=40
            )
        text = f"요약: {prompt[:50]}"
        if on_delta is not None:
            # 실제 공급자처럼 두 조각으로 나눠 보낸다
            half = len(text) // 2
            on_delta(text[:half])
            on_delta(text[half:])
        return LlmResult(text=text, model=model, input_tokens=50, output_tokens=10)

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn:
        self.calls.append({"kind": "chat", "messages": len(messages), "system": system})
        turn = self.script.pop(0)(messages) if self.script else ChatTurn(text="(스크립트 없음)")
        if turn.text and on_text is not None:
            on_text(turn.text)
        return turn

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append({"kind": "embed", "n": len(texts)})
        return [fake_embedding(t) for t in texts]


_counter = 0


def tool_turn(text: str, *calls: tuple[str, dict[str, Any]]) -> Callable[[list[Message]], ChatTurn]:
    def _turn(_: list[Message]) -> ChatTurn:
        global _counter
        tcs = []
        for name, args in calls:
            _counter += 1
            tcs.append(ToolCall(id=f"call_{_counter}", name=name, input=args))
        return ChatTurn(text=text, tool_calls=tcs, stop_reason="tool_use" if tcs else "end_turn")

    return _turn


def text_turn(text: str) -> Callable[[list[Message]], ChatTurn]:
    return tool_turn(text)


def last_tool_result(messages: list[Message], name: str) -> dict[str, Any]:
    for m in reversed(messages):
        if m.get("role") == "tool" and m.get("name") == name:
            data = json.loads(m["content"])
            return data if isinstance(data, dict) else {}
    return {}
