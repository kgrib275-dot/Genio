"""NodeSpec 인터페이스와 레지스트리.

모든 노드(기본·마켓)는 NodeSpec(type, input_schema, output_schema, ui_schema, run)으로만 등록한다.
노드는 외부 자원(LLM, HTTP, 지식베이스, 커넥터, 코드 실행)을 NodeServices로만 쓴다.
그래서 이 패키지는 api 패키지에 의존하지 않는다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

JsonSchema = dict[str, Any]


class NodeError(Exception):
    """노드 실행 실패. message는 사용자에게 보여도 되는 한국어 문장."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass
class LlmResult:
    text: str
    data: dict[str, Any] | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class NodeServices(Protocol):
    def llm_complete(
        self,
        *,
        provider: str,
        model: str | None,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: JsonSchema | None,
    ) -> LlmResult: ...

    def http_request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: Any,
    ) -> dict[str, Any]: ...

    def kb_search(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        method: str | None = None,
        score_threshold: float | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def run_connector(
        self,
        *,
        connector: str,
        credential_id: str,
        action: str,
        params: dict[str, Any],
    ) -> dict[str, Any]: ...

    def run_code(self, *, code: str, inputs: dict[str, Any]) -> dict[str, Any]: ...

    # v0.2
    def read_file(self, *, file_id: str) -> tuple[str, str, bytes]:
        """(파일 이름, MIME, 내용)"""
        ...

    def extract_text(self, *, filename: str, mime: str, content: bytes) -> str: ...

    def run_agent(
        self,
        *,
        provider: str,
        model: str | None,
        instruction: str,
        query: str,
        tools: list[dict[str, Any]],
        max_iterations: int,
    ) -> dict[str, Any]: ...


@dataclass
class NodeContext:
    """노드 실행 시 엔진이 넘겨주는 정보. 비밀값은 담지 않는다."""

    run_id: str
    node_id: str
    run_input: dict[str, Any]
    outputs: dict[str, dict[str, Any]]
    services: NodeServices
    render: Callable[[str], str]
    render_value: Callable[[Any], Any]
    evaluate: Callable[[str], Any]
    logs: list[str] = field(default_factory=list)
    # v0.2: 범위(item, index, loop 등)를 더한 하위 컨텍스트를 만든다(iteration·loop용)
    scoped: Callable[[dict[str, Any]], "NodeContext"] | None = None

    def log(self, message: str) -> None:
        self.logs.append(message)

    def with_scope(self, extra: dict[str, Any]) -> "NodeContext":
        if self.scoped is None:
            raise NodeError("이 노드는 하위 동작을 실행할 수 없어요.")
        return self.scoped(extra)


@dataclass
class NodeResult:
    output: dict[str, Any] = field(default_factory=dict)
    # condition 노드: 선택된 분기 핸들(case id)
    handle: str | None = None
    # approval 노드: 승인 대기 정보
    wait_approval: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[[dict[str, Any], NodeContext], NodeResult]
OutputsFn = Callable[[dict[str, Any]], list[str] | None]


@dataclass(frozen=True)
class NodeSpec:
    type: str
    label: str
    category: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    ui_schema: JsonSchema
    run: RunFn
    # data를 보고 출력 필드 이름 목록을 돌려준다. None이면 검사하지 않는다.
    outputs: OutputsFn | None = None
    # 재시도(지수 백오프) 횟수
    retries: int = 0
    source: str = "builtin"

    def describe(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "ui_schema": self.ui_schema,
            "source": self.source,
        }


class NodeRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, NodeSpec] = {}

    def register(self, spec: NodeSpec, *, replace: bool = False) -> None:
        if spec.type in self._specs and not replace:
            raise ValueError(f"이미 등록된 노드 타입입니다: {spec.type}")
        self._specs[spec.type] = spec

    def unregister(self, node_type: str) -> None:
        self._specs.pop(node_type, None)

    def get(self, node_type: str) -> NodeSpec | None:
        return self._specs.get(node_type)

    def types(self) -> list[str]:
        return sorted(self._specs)

    def all(self) -> list[NodeSpec]:
        return [self._specs[t] for t in self.types()]


registry = NodeRegistry()
