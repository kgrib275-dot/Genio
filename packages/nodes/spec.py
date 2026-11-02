"""NodeSpec 인터페이스와 레지스트리.

필드 구성(type, input_schema, output_schema, ui_schema, run)은 CLAUDE.md 규칙을 따른다.
실제 노드 6종과 실행 컨텍스트 세부는 docs/design.md 확정 후 2단계에서 채운다.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class NodeContext:
    """노드 실행 시 엔진이 넘겨주는 정보. 비밀값은 담지 않고 참조 ID만 담는다."""

    run_id: str
    node_id: str
    variables: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[[dict[str, Any], NodeContext], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class NodeSpec:
    type: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    ui_schema: JsonSchema
    run: RunFn


class NodeRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, NodeSpec] = {}

    def register(self, spec: NodeSpec) -> None:
        if spec.type in self._specs:
            raise ValueError(f"이미 등록된 노드 타입입니다: {spec.type}")
        self._specs[spec.type] = spec

    def get(self, node_type: str) -> NodeSpec:
        return self._specs[node_type]

    def types(self) -> list[str]:
        return sorted(self._specs)


registry = NodeRegistry()
