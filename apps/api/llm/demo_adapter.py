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
        """흐름 만들기 데모: 요청에 맞는 짧은 완성 흐름을 툴로 그린다(읽기 → 단계 더하기 → 결과 잇기 → 검사)."""
        start = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
        request = str(messages[start].get("content") or "") if messages else ""
        done = [m for m in messages[start + 1 :] if m["role"] == "tool"]
        called = [str(m.get("name")) for m in done]
        plan, kind = _demo_plan(request)
        n = len(called)

        def call(name: str, args: dict[str, Any], text: str) -> ChatTurn:
            return ChatTurn(
                text=text,
                tool_calls=[ToolCall(id=f"demo_{uuid.uuid4().hex[:10]}", name=name, input=args)],
                stop_reason="tool_use",
                model=DEMO_MODEL,
            )

        def payload(msg: Message) -> dict[str, Any]:
            try:  # 툴 결과 뒤에 '지금 흐름 요약' 글이 붙을 수 있어 앞쪽 JSON만 읽는다
                out, _ = json.JSONDecoder().raw_decode(str(msg.get("content") or "{}").lstrip())
            except ValueError:
                return {}
            return out if isinstance(out, dict) else {}

        if n == 0:
            return call("get_graph", {}, f"{DEMO_TAG} 지금 흐름을 먼저 읽어 볼게요.")
        graph = payload(done[0]).get("graph") or {}
        nodes = [x for x in graph.get("nodes", []) if isinstance(x, dict)]
        if n == 1 and len(nodes) > 2:
            return ChatTurn(
                text=f"{DEMO_TAG} 이미 단계가 여럿 있어서 건드리지 않았어요. {DEMO_NOTE}",
                model=DEMO_MODEL,
            )
        first = next((x for x in nodes if x.get("type") == "input"), None)
        out_node = next((x for x in nodes if x.get("type") == "output"), None)
        added = [
            str((payload(m).get("data") or payload(m)).get("node_id") or "")
            for m, name in zip(done, called, strict=False)
            if name == "add_node"
        ]
        if n <= len(plan):
            step = plan[n - 1]
            llm_ids = [a for a, st in zip(added, plan, strict=False) if st["type"] == "llm"]
            data = {
                k: (v.replace("@LLM", llm_ids[-1]) if isinstance(v, str) and llm_ids else v)
                for k, v in step["data"].items()
            }
            args: dict[str, Any] = {"type": step["type"], "data": data}
            prev = added[-1] if added else (str(first["id"]) if first and first.get("id") else "")
            if prev:
                args["after"] = prev
            return call("add_node", args, step["say"])
        if n == len(plan) + 1:
            last = next((a for a, st in zip(added, plan, strict=False) if st["type"] == "llm"), "")
            if out_node and out_node.get("id") and last:
                return call(
                    "update_node",
                    {"id": out_node["id"], "data": {"template": "{{" + last + ".text}}"}},
                    "마지막 결과가 이 단계의 답을 보여 주도록 이을게요.",
                )
            return call("validate", {}, "잘 연결됐는지 검사할게요.")
        if n == len(plan) + 2 and called[-1] != "validate":
            return call("validate", {}, "잘 연결됐는지 검사할게요.")
        return ChatTurn(text=f"{DEMO_TAG} {_demo_summary(kind)} {DEMO_NOTE}", model=DEMO_MODEL)


def _demo_plan(request: str) -> tuple[list[dict[str, Any]], str]:
    """요청에 든 말로 데모 흐름을 고른다. 데모라서 내용은 짧고 고정이다."""
    text = request.replace(" ", "")
    if any(k in text for k in ("승인", "결재")):
        return (
            [
                {
                    "type": "llm",
                    "say": "먼저 내용을 정리해 초안을 쓰는 단계를 더할게요.",
                    "data": {
                        "label": "초안 쓰기",
                        "provider": "default",
                        "system": "요청 내용을 보기 좋게 정리해 초안을 써 주세요.",
                        "prompt": "{{n1.message}}",
                    },
                },
                {
                    "type": "approval",
                    "say": "사람이 확인하고 승인하는 단계를 이어 붙일게요.",
                    "data": {
                        "label": "담당자 승인",
                        "message": "아래 내용을 확인하고 승인해 주세요.\n\n{{@LLM.text}}",
                        "branch": False,
                    },
                },
            ],
            "approve",
        )
    if any(k in text for k in ("분류", "나눠", "담당", "배정")):
        return (
            [
                {
                    "type": "llm",
                    "say": "내용을 읽고 종류를 나누는 단계를 더할게요.",
                    "data": {
                        "label": "종류 나누기",
                        "provider": "default",
                        "system": "문의를 결제·배송·기술·기타 중 하나로 나누고 이유를 한 줄로 적어 주세요.",
                        "prompt": "{{n1.message}}",
                    },
                }
            ],
            "classify",
        )
    if any(k in text for k in ("요약", "정리", "회의", "보고")):
        return (
            [
                {
                    "type": "llm",
                    "say": "내용을 간추리는 단계를 더할게요.",
                    "data": {
                        "label": "간추리기",
                        "provider": "default",
                        "system": "받은 글을 핵심 세 줄과 할 일 목록으로 정리해 주세요.",
                        "prompt": "{{n1.message}}",
                    },
                }
            ],
            "summarize",
        )
    return (
        [
            {
                "type": "llm",
                "say": "질문에 답하는 단계를 더할게요.",
                "data": {
                    "label": "답변 쓰기",
                    "provider": "default",
                    "system": "당신은 친절한 사내 도우미입니다. 짧고 정확하게 답하세요.",
                    "prompt": "질문: {{n1.message}}",
                },
            }
        ],
        "answer",
    )


def _demo_summary(kind: str) -> str:
    return {
        "approve": "초안을 쓰고 담당자가 승인하는 흐름을 그렸어요.",
        "classify": "들어온 내용을 종류별로 나누는 흐름을 그렸어요.",
        "summarize": "받은 글을 간추리는 흐름을 그렸어요.",
        "answer": "질문에 답하는 흐름을 그렸어요.",
    }.get(kind, "간단한 흐름을 그렸어요.")
