"""그래프 검증(설계서 §4): 형식, 노드 타입, 노드 설정, 순환, input 1개·output ≥1개,
참조 변수, 분기 핸들, 병렬 분기 금지, 커넥터 연결 정보·지식베이스 존재."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from api.engine.templating import iter_refs
from api.schemas.graph import Graph, GraphError, ValidationResult
from nodes import NodeRegistry, NodeSpec

# 노드 설정에 담기지만 검증 대상에서 빼는 키(캔버스 UI용)
_UI_KEYS = {"label", "note", "_retry", "_on_error", "_default"}
# 그래프 바깥에서 쓸 수 있는 예약 이름
RESERVED_SCOPES = {"input", "vars", "env", "conv", "item", "index", "loop"}


@dataclass
class ValidationEnv:
    registry: NodeRegistry
    # 워크스페이스에서 쓸 수 있는 노드 타입(설치된 마켓 노드 포함). None이면 레지스트리 전체
    allowed_types: set[str] | None = None
    # 연결 정보 id → 커넥터 key. None이면 검사하지 않음
    credentials: dict[str, str] | None = None
    connectors: set[str] | None = None
    knowledge_bases: set[str] | None = None
    errors: list[GraphError] = field(default_factory=list)


def branch_handles(node_type: str, data: dict[str, Any]) -> set[str] | None:
    """갈림길 노드의 출구 이름. 갈림길이 아니면 None."""
    if node_type == "condition":
        h = {str(c.get("id")) for c in data.get("cases", []) if c.get("id")}
        h.add(str(data.get("else") or "else"))
        return h
    if node_type == "question_classifier":
        return {str(c.get("id")) for c in data.get("classes", []) if c.get("id")}
    return None


def ordered_branch_handles(node_type: str, data: dict[str, Any]) -> list[str]:
    """갈림길 출구를 화면 순서대로(끈 블록이 고르는 '첫 번째 출구'용)."""
    if node_type == "condition":
        ids = [str(c.get("id")) for c in data.get("cases", []) if c.get("id")]
        return [*ids, str(data.get("else") or "else")]
    if node_type == "question_classifier":
        return [str(c.get("id")) for c in data.get("classes", []) if c.get("id")]
    return []


def _schema_errors(spec: NodeSpec, node_id: str, data: dict[str, Any]) -> list[GraphError]:
    schema = spec.input_schema
    props = schema.get("properties", {})
    out: list[GraphError] = []
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        if err.validator == "required":
            missing = [k for k in schema.get("required", []) if k not in data]
            for key in missing:
                title = props.get(key, {}).get("title", key)
                out.append(
                    GraphError(node_id=node_id, field=key, message=f"'{title}' 칸을 채워 주세요.")
                )
            continue
        key = str(err.path[0]) if err.path else None
        title = props.get(key, {}).get("title", key) if key else "설정"
        out.append(
            GraphError(node_id=node_id, field=key, message=f"'{title}' 값의 형식이 맞지 않아요.")
        )
    # 같은 오류가 여러 번 나올 수 있어 중복 제거
    seen: set[tuple[str | None, str]] = set()
    uniq = []
    for e in out:
        k = (e.field, e.message)
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def validate_graph(raw: dict[str, Any], env: ValidationEnv) -> ValidationResult:
    try:
        graph = Graph.model_validate(raw)
    except ValidationError as exc:
        parse_errors = []
        for err in exc.errors()[:20]:
            loc = ".".join(str(p) for p in err["loc"])
            parse_errors.append(GraphError(message=f"흐름 형식이 올바르지 않아요({loc})."))
        return ValidationResult(valid=False, errors=parse_errors)

    errors: list[GraphError] = []
    nodes = {n.id: n for n in graph.nodes}

    if len(nodes) != len(graph.nodes):
        errors.append(
            GraphError(message="같은 id를 가진 노드가 있어요. 노드 id는 서로 달라야 해요.")
        )
    edge_ids = [e.id for e in graph.edges]
    if len(set(edge_ids)) != len(edge_ids):
        errors.append(GraphError(message="같은 id를 가진 연결선이 있어요."))

    # 노드 타입·설정
    specs: dict[str, NodeSpec] = {}
    for node in graph.nodes:
        spec = env.registry.get(node.type)
        if node.disabled and node.type == "input":
            errors.append(
                GraphError(node_id=node.id, message="입력 블록은 끌 수 없어요. 다시 켜 주세요.")
            )
        if node.disabled and spec is None:
            continue  # 꺼 둔 블록은 설치되지 않은 마켓 블록이어도 괜찮다
        if spec is None or (env.allowed_types is not None and node.type not in env.allowed_types):
            errors.append(
                GraphError(
                    node_id=node.id,
                    message=f"'{node.type}' 노드는 이 워크스페이스에서 쓸 수 없어요. 마켓에서 설치했는지 확인하세요.",
                )
            )
            continue
        specs[node.id] = spec
        if node.disabled:
            continue
        data = {k: v for k, v in node.data.items() if k not in _UI_KEYS}
        errors.extend(_schema_errors(spec, node.id, data))

    inputs = [n for n in graph.nodes if n.type == "input"]
    outputs = [n for n in graph.nodes if n.type == "output" and not n.disabled]
    if len(inputs) != 1:
        errors.append(GraphError(message=f"입력 노드는 정확히 1개여야 해요(지금 {len(inputs)}개)."))
    if not outputs:
        errors.append(GraphError(message="켜져 있는 결과 노드가 최소 1개 있어야 해요."))

    # 연결선
    out_edges: dict[str, list[Any]] = defaultdict(list)
    in_deg: dict[str, int] = {nid: 0 for nid in nodes}
    for e in graph.edges:
        bad = False
        for end in (e.source, e.target):
            if end not in nodes:
                errors.append(GraphError(message=f"연결선 {e.id}가 없는 노드 '{end}'를 가리켜요."))
                bad = True
        if bad:
            continue
        if e.source == e.target:
            errors.append(
                GraphError(node_id=e.source, message="노드가 자기 자신으로 연결돼 있어요.")
            )
            continue
        out_edges[e.source].append(e)
        in_deg[e.target] += 1

    for nid, edges in out_edges.items():
        node = nodes[nid]
        branches = branch_handles(node.type, node.data)
        can_fail = node.data.get("_on_error") == "branch"
        used: set[str] = set()
        plain = 0
        for e in edges:
            h = e.source_handle or ""
            if h == "fail":
                if not can_fail:
                    errors.append(
                        GraphError(
                            node_id=nid,
                            message="'실패' 길을 쓰려면 이 노드의 '실패했을 때'를 '실패 길로 보내기'로 바꿔 주세요.",
                        )
                    )
                elif "fail" in used:
                    errors.append(
                        GraphError(node_id=nid, message="'실패' 길은 한 곳으로만 이을 수 있어요.")
                    )
                used.add("fail")
                continue
            if branches is not None:
                if not h:
                    errors.append(
                        GraphError(
                            node_id=nid, message="갈림길에서 나가는 선은 어떤 분기인지 골라야 해요."
                        )
                    )
                elif h not in branches:
                    errors.append(GraphError(node_id=nid, message=f"'{h}' 분기가 목록에 없어요."))
                elif h in used:
                    errors.append(
                        GraphError(
                            node_id=nid,
                            message=f"'{h}' 분기에서 두 곳으로 갈 수 없어요(병렬 분기 미지원).",
                        )
                    )
                used.add(h)
            else:
                if h:
                    errors.append(
                        GraphError(node_id=nid, message=f"이 노드에는 '{h}' 출구가 없어요.")
                    )
                plain += 1
        if plain > 1:
            errors.append(
                GraphError(
                    node_id=nid,
                    message="한 노드에서 여러 곳으로 동시에 갈 수 없어요(병렬 분기는 아직 지원하지 않아요).",
                )
            )

    # 순환 검사(Kahn)
    indeg = dict(in_deg)
    queue = deque(n for n, d in indeg.items() if d == 0)
    visited = 0
    while queue:
        cur = queue.popleft()
        visited += 1
        for e in out_edges.get(cur, []):
            indeg[e.target] -= 1
            if indeg[e.target] == 0:
                queue.append(e.target)
    if visited != len(nodes):
        cyclic = [n for n, d in indeg.items() if d > 0]
        errors.append(
            GraphError(
                node_id=cyclic[0] if cyclic else None,
                message="흐름이 빙글빙글 도는 순환 연결이 있어요. 되돌아가는 선을 지워 주세요.",
            )
        )
        return ValidationResult(valid=False, errors=errors)

    # 조상 집합(참조 검사용)
    parents: dict[str, set[str]] = defaultdict(set)
    for src, edges in out_edges.items():
        for e in edges:
            parents[e.target].add(src)
    ancestors: dict[str, set[str]] = {}

    def _anc(nid: str) -> set[str]:
        if nid in ancestors:
            return ancestors[nid]
        acc: set[str] = set()
        for p in parents.get(nid, set()):
            acc.add(p)
            acc |= _anc(p)
        ancestors[nid] = acc
        return acc

    # 입력 노드에서 닿지 않는 노드
    if len(inputs) == 1:
        start = inputs[0].id
        for node in graph.nodes:
            if node.id != start and start not in _anc(node.id):
                errors.append(
                    GraphError(
                        node_id=node.id,
                        message="입력 노드에서 이어지지 않은 노드예요. 선으로 연결해 주세요.",
                    )
                )

    # 참조 변수
    for node in graph.nodes:
        if node.disabled:
            continue
        refs = set(iter_refs({k: v for k, v in node.data.items() if k not in _UI_KEYS}))
        for ref_node, ref_field in refs:
            if ref_node in RESERVED_SCOPES:
                continue
            if ref_node not in nodes:
                errors.append(
                    GraphError(
                        node_id=node.id, message=f"없는 노드 '{ref_node}'의 값을 쓰고 있어요."
                    )
                )
                continue
            if ref_node not in _anc(node.id):
                errors.append(
                    GraphError(
                        node_id=node.id,
                        message=f"'{ref_node}' 노드는 이 노드보다 앞에 있지 않아 값을 쓸 수 없어요.",
                    )
                )
                continue
            spec = specs.get(ref_node)
            if nodes[ref_node].disabled:
                continue  # 끈 블록은 앞 단계 값을 그대로 넘기므로 이름을 미리 알 수 없다
            if spec is not None and spec.outputs is not None and ref_field:
                fields = spec.outputs(nodes[ref_node].data)
                if fields is not None and nodes[ref_node].data.get("_on_error") in (
                    "default",
                    "branch",
                ):
                    fields = [*fields, "error"]
                if fields is not None and ref_field not in fields:
                    errors.append(
                        GraphError(
                            node_id=node.id,
                            message=f"'{ref_node}' 노드에는 '{ref_field}' 값이 없어요. 쓸 수 있는 값: {', '.join(fields) or '없음'}",
                        )
                    )

    # 커넥터·지식베이스·v0.4 블록
    for node in graph.nodes:
        if node.disabled:
            continue
        if node.type == "data_table":
            op = str(node.data.get("operation") or "")
            if op in ("upsert", "get") and not str(node.data.get("row_key") or "").strip():
                errors.append(
                    GraphError(
                        node_id=node.id,
                        field="row_key",
                        message="덮어쓰기·가져오기는 '고유 키' 칸을 채워야 해요.",
                    )
                )
            if op == "delete" and not (
                str(node.data.get("row_key") or "").strip() or node.data.get("filter")
            ):
                errors.append(
                    GraphError(
                        node_id=node.id,
                        field="filter",
                        message="지우기는 '고유 키'나 '찾는 조건'을 채워야 해요(전체 지우기는 화면에서만).",
                    )
                )
        if node.type == "connector":
            key = str(node.data.get("connector") or "")
            cred = str(node.data.get("credential_id") or "")
            if env.connectors is not None and key and key not in env.connectors:
                errors.append(
                    GraphError(
                        node_id=node.id,
                        field="connector",
                        message=f"'{key}' 서비스가 설치되어 있지 않아요. 마켓에서 설치해 주세요.",
                    )
                )
            if env.credentials is not None:
                if not cred:
                    errors.append(
                        GraphError(
                            node_id=node.id,
                            field="credential_id",
                            message="연결 정보를 골라 주세요.",
                        )
                    )
                elif cred not in env.credentials:
                    errors.append(
                        GraphError(
                            node_id=node.id,
                            field="credential_id",
                            message="선택한 연결 정보가 없어요. 연결 정보 화면에서 다시 골라 주세요.",
                        )
                    )
                elif key and env.credentials[cred] != key:
                    errors.append(
                        GraphError(
                            node_id=node.id,
                            field="credential_id",
                            message="다른 서비스의 연결 정보가 선택돼 있어요.",
                        )
                    )
        if node.type == "knowledge_search" and env.knowledge_bases is not None:
            kb = str(node.data.get("kb_id") or "")
            if kb and kb not in env.knowledge_bases:
                errors.append(
                    GraphError(
                        node_id=node.id, field="kb_id", message="선택한 지식베이스가 없어요."
                    )
                )

    return ValidationResult(valid=not errors, errors=errors)


def topo_order(graph: Graph) -> list[str]:
    indeg = {n.id: 0 for n in graph.nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        if e.source in indeg and e.target in indeg:
            adj[e.source].append(e.target)
            indeg[e.target] += 1
    queue = deque(n.id for n in graph.nodes if indeg[n.id] == 0)
    order = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for t in adj[cur]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    return order
