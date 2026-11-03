"""빌더 컨텍스트용 그래프 요약(설계서 §6-1, §6-3): 순번·id·type·label과 연결."""

from api.engine.validator import topo_order
from api.schemas.graph import Graph


def summarize(graph: Graph) -> str:
    if not graph.nodes:
        return "(비어 있는 흐름)"
    order = topo_order(graph)
    rest = [n.id for n in graph.nodes if n.id not in order]
    lines = []
    for i, nid in enumerate(order + rest, start=1):
        node = graph.node(nid)
        if node is None:
            continue
        label = node.data.get("label") or ""
        lines.append(f"{i}. {node.id} [{node.type}] {label}".rstrip())
    edges = []
    for e in graph.edges:
        via = f"({e.source_handle})" if e.source_handle else ""
        edges.append(f"{e.source}{via}→{e.target}")
    return "\n".join(lines) + ("\n연결: " + ", ".join(edges) if edges else "\n연결: 없음")
