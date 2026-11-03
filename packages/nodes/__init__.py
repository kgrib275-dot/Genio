"""노드 타입 레지스트리. 모든 노드(기본·마켓)는 NodeSpec으로만 등록한다."""

from nodes.builtin import BUILTIN_SPECS, register_builtins
from nodes.builtin_v02 import register_v02
from nodes.spec import (
    LlmResult,
    NodeContext,
    NodeError,
    NodeRegistry,
    NodeResult,
    NodeServices,
    NodeSpec,
    registry,
)

register_builtins(registry)
register_v02(registry)

__all__ = [
    "BUILTIN_SPECS",
    "LlmResult",
    "NodeContext",
    "NodeError",
    "NodeRegistry",
    "NodeResult",
    "NodeServices",
    "NodeSpec",
    "registry",
]
