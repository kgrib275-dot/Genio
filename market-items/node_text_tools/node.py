"""마켓 노드 예시: 글자 다듬기. 기본 노드와 같은 NodeSpec 인터페이스로 등록한다."""

import re
from typing import Any

from nodes.spec import NodeContext, NodeError, NodeResult, NodeSpec


def run(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    text = ctx.render(str(data.get("text", "")))
    op = str(data.get("operation") or "trim")
    if op == "trim":
        out = re.sub(r"\s+", " ", text).strip()
    elif op == "upper":
        out = text.upper()
    elif op == "lower":
        out = text.lower()
    elif op == "replace":
        out = text.replace(str(data.get("find", "")), str(data.get("replace_with", "")))
    elif op == "count":
        out = text
    else:
        raise NodeError("알 수 없는 동작이에요: " + op)
    return NodeResult(output={"text": out, "length": len(out)})


SPEC = NodeSpec(
    type="text_tools",
    label="글자 다듬기",
    category="마켓",
    description="글의 공백을 정리하거나, 대소문자를 바꾸거나, 찾아 바꾸고, 글자 수를 세요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": {"type": "string", "title": "이름"},
            "text": {"type": "string", "title": "대상 글"},
            "operation": {
                "type": "string",
                "title": "동작",
                "enum": ["trim", "upper", "lower", "replace", "count"],
                "default": "trim",
            },
            "find": {"type": "string", "title": "찾을 글(바꾸기)"},
            "replace_with": {"type": "string", "title": "바꿀 글(바꾸기)"},
        },
        "required": ["text", "operation"],
    },
    output_schema={"type": "object", "properties": {"text": {"type": "string"}, "length": {"type": "integer"}}},
    ui_schema={"text": {"ui:widget": "textarea"}},
    run=run,
    outputs=lambda d: ["text", "length"],
    source="market",
)
