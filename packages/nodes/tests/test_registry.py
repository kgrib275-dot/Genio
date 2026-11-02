from typing import Any

import pytest

from nodes.spec import NodeContext, NodeRegistry, NodeSpec


async def _echo(inputs: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    return inputs


def _spec(node_type: str = "echo") -> NodeSpec:
    return NodeSpec(
        type=node_type,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        ui_schema={},
        run=_echo,
    )


def test_register_and_get() -> None:
    reg = NodeRegistry()
    reg.register(_spec())
    assert reg.types() == ["echo"]
    assert reg.get("echo").type == "echo"


def test_duplicate_type_rejected() -> None:
    reg = NodeRegistry()
    reg.register(_spec())
    with pytest.raises(ValueError):
        reg.register(_spec())
