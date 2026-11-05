"""스니펫(v0.8): 자주 쓰는 단계 묶음을 저장해 다른 흐름에 끼워 넣는다.

저장할 때 다음을 정리한다.
- 고른 단계끼리 이어진 연결만 남기고, 바깥으로 나가는 연결은 버린다.
- 연결 정보·지식베이스·데이터 표처럼 워크스페이스마다 다른 '고르는 값'은 비운다(다시 골라야 해요).
- 고르지 않은 바깥 단계의 값을 쓰는 칸(`{{n5.text}}`)은 `{{__outer.n5.text}}`로 바꿔 둔다.
  끼워 넣은 흐름에 우연히 같은 id의 단계가 있어도 엉뚱한 값이 조용히 이어지지 않고,
  검사에서 '없는 단계'로 바로 드러나게 하려는 것이다.
"""

import re
from typing import Any

from pydantic import ValidationError

from api.core.errors import AppError
from api.engine.validator import RESERVED_SCOPES
from api.models import Snippet
from api.schemas.graph import Graph

MAX_NODES = 50
MAX_SNIPPETS = 200
# 워크스페이스마다 다른 값이라 스니펫에는 담지 않는다
RESELECT_KEYS = {
    "credential_id": "연결 정보",
    "kb_id": "지식베이스",
    "table_id": "데이터 표",
    "app_id": "다른 앱",
    "assignee_user_id": "담당자",
    "file_id": "파일",
}
_REF = re.compile(r"\{\{(\s*)([A-Za-z_][A-Za-z0-9_]*)(?=[.\s}|])")


def _scrub(value: Any, removed: set[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in RESELECT_KEYS:
                if v not in (None, "", [], {}):
                    removed.add(RESELECT_KEYS[k])
                continue
            out[k] = _scrub(v, removed)
        return out
    if isinstance(value, list):
        return [_scrub(v, removed) for v in value]
    return value


def _neutralize(value: Any, inside: set[str], outer: set[str]) -> Any:
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            ref = m.group(2)
            if ref in inside or ref in RESERVED_SCOPES or ref == "__outer":
                return m.group(0)
            outer.add(ref)
            return f"{{{{{m.group(1)}__outer.{ref}"

        return _REF.sub(sub, value)
    if isinstance(value, list):
        return [_neutralize(v, inside, outer) for v in value]
    if isinstance(value, dict):
        return {k: _neutralize(v, inside, outer) for k, v in value.items()}
    return value


def build_snippet_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """캔버스에서 고른 단계·연결을 스니펫으로 정리한다. 올바르지 않으면 두 줄 오류."""
    if not nodes:
        raise AppError(
            422, "스니펫으로 저장할 단계가 없어요.", "캔버스에서 단계를 하나 이상 고르세요."
        )
    if len(nodes) > MAX_NODES:
        raise AppError(
            422,
            f"스니펫은 단계 {MAX_NODES}개까지 담을 수 있어요.",
            "더 작은 묶음으로 나눠서 저장해 주세요.",
        )
    try:
        graph = Graph.model_validate({"nodes": nodes, "edges": edges})
    except ValidationError:
        raise AppError(
            422,
            "고른 단계의 형식이 올바르지 않아요.",
            "캔버스를 새로 고친 뒤 다시 골라 저장하세요.",
        ) from None
    ids = [n.id for n in graph.nodes]
    if len(set(ids)) != len(ids):
        raise AppError(
            422, "같은 id의 단계가 겹쳐 있어요.", "캔버스를 새로 고친 뒤 다시 시도하세요."
        )
    if any(n.type == "input" for n in graph.nodes):
        raise AppError(
            422,
            "시작(입력) 단계는 스니펫에 담을 수 없어요.",
            "시작 단계를 빼고 나머지 단계만 골라 저장하세요.",
        )
    inside = set(ids)
    keep_edges = [e for e in graph.edges if e.source in inside and e.target in inside]
    reselect: list[dict[str, Any]] = []
    outer_nodes: list[str] = []
    out_nodes: list[dict[str, Any]] = []
    for n in graph.nodes:
        removed: set[str] = set()
        outer: set[str] = set()
        data = _scrub(n.data, removed)
        data = _neutralize(data, inside, outer)
        label = str(data.get("label") or n.type)
        if removed:
            reselect.append({"node_id": n.id, "label": label, "fields": sorted(removed)})
        if outer:
            outer_nodes.append(label)
        d = n.model_dump(exclude_none=True)
        d["data"] = data
        out_nodes.append(d)
    return {
        "nodes": out_nodes,
        "edges": [e.model_dump(by_alias=True, exclude_none=True) for e in keep_edges],
        "reselect": reselect,
        "outer_refs": outer_nodes,
    }


def snippet_dict(s: Snippet, *, with_graph: bool = False) -> dict[str, Any]:
    g = s.graph or {}
    reselect = [
        f"{r.get('label')}: {', '.join(r.get('fields') or [])}" for r in g.get("reselect") or []
    ]
    out: dict[str, Any] = {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "node_count": len(g.get("nodes") or []),
        "node_types": sorted({str(n.get("type")) for n in g.get("nodes") or []}),
        "reselect": reselect,
        "outer_refs": list(g.get("outer_refs") or []),
        "created_by": s.created_by,
        "created_at": s.created_at,
    }
    if with_graph:
        out["graph"] = {"nodes": g.get("nodes") or [], "edges": g.get("edges") or []}
    return out
