"""노드 타입 레지스트리. 모든 노드(기본·마켓)는 NodeSpec으로만 등록한다."""

from nodes.builtin import BUILTIN_SPECS, register_builtins
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
