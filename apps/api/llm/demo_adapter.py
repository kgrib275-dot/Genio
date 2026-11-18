"""데모 AI: API 키 없이 화면과 흐름을 훑어볼 수 있는 가짜 AI(공급자 이름 `demo`).

- 실제 AI가 아니다. 질문을 알아듣지 못하고, 같은 입력이면 늘 같은 예시 답을 낸다. 답에는 '(데모 응답)'을 붙여
  데모라는 것을 숨기지 않는다.
- 흐름 만들기(빌더)는 질문과 상관없이 '데모 단계'가 든 아주 간단한 흐름만 만든다.
- 지식 검색용 임베딩은 단어 해시로 만들어, 같은 낱말이 많이 겹치는 글끼리 가깝게 나온다(의미는 모른다).
- 실제 키를 가진 연결을 등록하면 그 연결을 쓰면 된다. 데모 연결은 지워도 되고 그대로 둬도 된다.
"""

import hashlib
import json
import math
import re
import uuid
from typing import Any

from api.llm.base import ChatTurn, Message, OnText, ToolCall, ToolDef, parse_json_object
from nodes import LlmResult

DEMO_TAG = "(데모 응답)"
DEMO_MODEL = "demo-1"
DEMO_NOTE = "실제 AI가 아니라 예시 답이에요. 키가 있는 AI 연결을 등록하면 진짜 답이 나와요."


def embed_text(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for word in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()):
        for gram in {word, *(word[i : i + 2] for i in range(max(len(word) - 1, 0)))}:
            h = int(hashlib.sha256(gram.encode()).hexdigest(), 16)
            vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _sample(schema: dict[str, Any], key: str = "") -> Any:
    """JSON Schema에 맞는 예시 값."""
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _sample(v, k) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_sample(schema.get("items") or {}, key)]
    if t in ("number", "integer"):
        return 0
    if t == "boolean":
        return True
    return f"데모 {key}".strip()


def _demo_answer(prompt: str) -> str:
    ctx = ""
    if "자료:" in prompt:  # 지식 검색 결과가 붙은 경우: 첫 줄을 근거로 보여 준다
        rest = prompt.split("자료:", 1)[1].strip().splitlines()
        ctx = rest[0][:80] if rest else ""
    question = re.sub(r"\s+", " ", prompt.split("자료:", 1)[0]).strip()[:60]
    if ctx:
        return f"{DEMO_TAG} 찾은 자료에는 '{ctx}'라고 적혀 있어요. ({DEMO_NOTE})"
    return f"{DEMO_TAG} '{question}'에 대한 예시 답이에요. {DEMO_NOTE}"


class DemoAdapter:
    provider = "demo"

    def __init__(self, api_key: str = "", base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url

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
        if json_schema:
            text = json.dumps(_sample(json_schema), ensure_ascii=False)
            return LlmResult(
                text=text,
                data=parse_json_object(text),
                model=DEMO_MODEL,
                input_tokens=0,
                output_tokens=0,
            )
        text = _demo_answer(prompt)
        if on_delta is not None:
            half = len(text) // 2
            on_delta(text[:half])
            on_delta(text[half:])
        return LlmResult(text=text, model=DEMO_MODEL, input_tokens=0, output_tokens=0)

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        from api.models.entities import EMBEDDING_DIM

        return [embed_text(t, EMBEDDING_DIM) for t in texts]

    # ---- 대화(도구 호출) ----
    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn:
        names = {t.name for t in tools}
        if {"add_node", "validate", "get_graph"} <= names:
            turn = self._builder_turn(messages)
        else:
            last = next((m for m in reversed(messages) if m["role"] == "user"), {"content": ""})
            turn = ChatTurn(text=_demo_answer(str(last.get("content") or "")), model=DEMO_MODEL)
        if on_text is not None and turn.text:
            on_text(turn.text)
        return turn

    def _builder_turn(self, messages: list[Message]) -> ChatTurn:
        """흐름 만들기 데모: 읽기 → '데모 단계' 하나 더하기 → 검사 → 안내, 순서로 툴을 부른다."""
        start = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
        done = [m for m in messages[start + 1 :] if m["role"] == "tool"]
        called = [str(m.get("name")) for m in done]

        def call(name: str, args: dict[str, Any], text: str) -> ChatTurn:
            return ChatTurn(
                text=text,
                tool_calls=[ToolCall(id=f"demo_{uuid.uuid4().hex[:10]}", name=name, input=args)],
                stop_reason="tool_use",
                model=DEMO_MODEL,
            )

        if not called:
            return call("get_graph", {}, f"{DEMO_TAG} 지금 흐름을 먼저 읽어 볼게요.")
        if called == ["get_graph"]:
            graph: dict[str, Any] = {}
            try:
                graph = json.loads(str(done[0].get("content") or "{}")).get("graph") or {}
            except ValueError:
                graph = {}
            if len(graph.get("nodes", [])) > 2:
                return ChatTurn(
                    text=f"{DEMO_TAG} 이미 단계가 여럿 있어서 건드리지 않았어요. {DEMO_NOTE}",
                    model=DEMO_MODEL,
                )
            # 입력 단계 바로 뒤에 끼워 넣어 연결이 끊기지 않게 한다
            first = next(
                (
                    n
                    for n in graph.get("nodes", [])
                    if isinstance(n, dict) and n.get("type") == "input"
                ),
                None,
            )
            args: dict[str, Any] = {
                "type": "template",
                "data": {"label": "데모 단계", "template": "데모로 만든 단계예요."},
            }
            if first and first.get("id"):
                args["after"] = first["id"]
            return call("add_node", args, "예시로 '데모 단계'를 하나 더할게요.")
        if called == ["get_graph", "add_node"]:
            return call("validate", {}, "잘 연결됐는지 검사할게요.")
        return ChatTurn(
            text=(
                f"{DEMO_TAG} 데모 모드라 질문과 상관없이 간단한 단계 하나만 더했어요. {DEMO_NOTE}"
            ),
            model=DEMO_MODEL,
        )
