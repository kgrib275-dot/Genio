"""워크플로우 그래프 스키마(설계서 §4)의 단일 정의.

프런트 타입은 이 모델의 JSON Schema에서 생성한다(`scripts/gen_types.py`). 다른 곳에 따로 쓰지 않는다.
노드별 data 형식은 각 NodeSpec의 input_schema가 정한다.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

NODE_TYPES = (
    "input",
    "llm",
    "condition",
    "http",
    "knowledge_search",
    "code",
    "connector",
    "approval",
    "output",
)


class Position(BaseModel):
    x: float = 0
    y: float = 0


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: str = Field(min_length=1, max_length=64)
    position: Position = Field(default_factory=Position)
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(min_length=1, max_length=64)
    source: str
    target: str
    source_handle: str | None = Field(default=None, alias="sourceHandle")
    target_handle: str | None = Field(default=None, alias="targetHandle")


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid", title="Graph")

    version: int = 1
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)

    def dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)

    def node(self, node_id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


class GraphError(BaseModel):
    node_id: str | None = None
    field: str | None = None
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[GraphError] = Field(default_factory=list)


def empty_graph() -> dict[str, Any]:
    return Graph().dump()


def starter_graph() -> dict[str, Any]:
    """새 앱의 기본 그래프: 입력 → 출력."""
    return Graph(
        nodes=[
            GraphNode(
                id="n1",
                type="input",
                position=Position(x=0, y=0),
                data={
                    "label": "사용자 입력",
                    "fields": [{"key": "message", "type": "text", "required": True}],
                },
            ),
            GraphNode(
                id="n2",
                type="output",
                position=Position(x=320, y=0),
                data={"label": "결과", "template": "{{n1.message}}"},
            ),
        ],
        edges=[GraphEdge(id="e1", source="n1", target="n2")],
    ).dump()
