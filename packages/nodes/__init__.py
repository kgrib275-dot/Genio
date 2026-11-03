"""노드 타입 레지스트리. 모든 노드(기본·마켓)는 NodeSpec으로만 등록한다."""

from nodes.builtin import BUILTIN_SPECS, register_builtins
from nodes.builtin_v02 import register_v02
from nodes.builtin_v04 import register_v04
from nodes.builtin_v05 import register_v05
from nodes.spec import (
    LlmResult,
    NodeContext,
    NodeError,
    NodeRegistry,
    NodeResult,
    NodeServices,
    NodeSpec,
    quote_block,
    registry,
)

register_builtins(registry)
register_v02(registry)
register_v04(registry)
register_v05(registry)

__all__ = [
    "BUILTIN_SPECS",
    "LlmResult",
    "NodeContext",
    "NodeError",
    "NodeRegistry",
    "NodeResult",
    "NodeServices",
    "NodeSpec",
    "quote_block",
    "registry",
]
