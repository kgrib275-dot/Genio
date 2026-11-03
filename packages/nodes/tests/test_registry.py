from typing import Any

import pytest

from nodes import BUILTIN_SPECS, registry
from nodes.spec import NodeContext, NodeRegistry, NodeResult, NodeSpec


def _echo(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    return NodeResult(output=data)


def _spec(node_type: str = "echo") -> NodeSpec:
    return NodeSpec(
        type=node_type,
        label="에코",
        category="테스트",
        description="입력을 그대로 돌려줘요.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        ui_schema={},
        run=_echo,
    )


def test_register_and_get() -> None:
    reg = NodeRegistry()
    reg.register(_spec())
    assert reg.types() == ["echo"]
    spec = reg.get("echo")
    assert spec is not None and spec.type == "echo"


def test_duplicate_type_rejected() -> None:
    reg = NodeRegistry()
    reg.register(_spec())
    with pytest.raises(ValueError):
        reg.register(_spec())
    reg.register(_spec(), replace=True)


def test_builtin_nine_types_registered() -> None:
    expected = {
        "input",
        "llm",
        "condition",
        "http",
        "knowledge_search",
        "code",
        "connector",
        "approval",
        "output",
    }
    assert {s.type for s in BUILTIN_SPECS} == expected
    assert expected <= set(registry.types())
    for spec in BUILTIN_SPECS:
        described = spec.describe()
        assert described["input_schema"]["type"] == "object"
        assert described["source"] == "builtin"
