"""작업본 3자 합치기(v0.9): 같은 앱을 두 사람이 동시에 고쳤을 때 겹치지 않는 변경은 자동으로 합친다.

base(둘이 같이 시작한 흐름), mine(내가 저장하려는 흐름), theirs(그 사이 서버에 저장된 흐름)를 비교한다.
- 단계·메모: 같은 칸(설정 항목)을 둘 다 다르게 고쳤을 때만 충돌. 위치(position)는 충돌로 보지 않고 내 것을 쓴다.
- 연결선: 한쪽만 더하거나 지우면 그대로 합치고, 같은 선을 서로 다르게 고쳤을 때만 충돌.
- 한쪽이 지운 단계를 다른 쪽이 고쳤으면 충돌('삭제 vs 수정').
- 합친 뒤 없는 단계를 가리키는 연결선은 지운다.
충돌이 있으면 합친 결과(merged)는 충돌 항목을 '상대(theirs)' 값으로 둔 상태이고, 사용자가 항목마다 고른다.
"""

import copy
from dataclasses import dataclass, field
from typing import Any

MISSING = object()
EDGE_KEYS = ("source", "target", "sourceHandle", "targetHandle")


@dataclass
class MergeResult:
    merged: dict[str, Any]
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    dropped_edges: int = 0
    auto_merged: bool = False


def _by_id(items: Any) -> dict[str, dict[str, Any]]:
    return {str(i["id"]): i for i in (items or []) if isinstance(i, dict) and "id" in i}


def _fields(item: dict[str, Any]) -> dict[str, Any]:
    """항목을 칸 단위로 편다: 맨 위 칸(type·position…)과 data.<키>."""
    out: dict[str, Any] = {}
    for k, v in item.items():
        if k == "data" and isinstance(v, dict):
            for dk, dv in v.items():
                out[f"data.{dk}"] = dv
        elif k != "id":
            out[k] = v
    return out


def _build(item_id: str, fields: dict[str, Any], has_data: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"id": item_id}
    data: dict[str, Any] = {}
    for k, v in fields.items():
        if k.startswith("data."):
            data[k[5:]] = v
        else:
            out[k] = v
    if data or has_data:
        out["data"] = data
    return out


def _conflict(
    kind: str, item_id: str, field_name: str, label: str, base: Any, mine: Any, theirs: Any
) -> dict[str, Any]:
    def clean(v: Any) -> Any:
        return None if v is MISSING else v

    return {
        "kind": kind,
        "node_id": item_id,
        "field": field_name,
        "label": label,
        "base": clean(base),
        "mine": clean(mine),
        "theirs": clean(theirs),
    }


def _label(item: dict[str, Any] | None, fallback: str) -> str:
    if item is None:
        return fallback
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    text = (data or {}).get("label") or item.get("text") or item.get("type") or fallback
    return str(text)[:60]


def _merge_items(
    kind: str,
    base: dict[str, dict[str, Any]],
    mine: dict[str, dict[str, Any]],
    theirs: dict[str, dict[str, Any]],
    order: list[str],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for iid in order:
        b, m, t = base.get(iid), mine.get(iid), theirs.get(iid)
        label = _label(t or m or b, iid)
        if m is None and t is None:
            continue
        if b is None:  # 새로 생긴 항목
            if m is not None and t is not None and m != t:
                conflicts.append(_conflict(kind, iid, "*", label, MISSING, m, t))
                out.append(t)
            else:
                out.append(copy.deepcopy(t if t is not None else m))  # type: ignore[arg-type]
            continue
        if m is None:  # 내가 지움
            if t is not None and t != b:
                conflicts.append(_conflict(kind, iid, "*", label, b, MISSING, t))
                out.append(t)
            continue
        if t is None:  # 상대가 지움
            if m != b:
                conflicts.append(_conflict(kind, iid, "*", label, b, m, MISSING))
            continue
        if m == t:
            out.append(copy.deepcopy(t))
            continue
        if kind == "edge":  # 연결선은 칸 단위로 나누지 않는다
            if m == b:
                out.append(copy.deepcopy(t))
            elif t == b:
                out.append(copy.deepcopy(m))
            else:
                conflicts.append(_conflict(kind, iid, "*", label, b, m, t))
                out.append(t)
            continue
        fb, fm, ft = _fields(b), _fields(m), _fields(t)
        result: dict[str, Any] = {}
        for key in dict.fromkeys([*ft, *fm]):
            bv, mv, tv = fb.get(key, MISSING), fm.get(key, MISSING), ft.get(key, MISSING)
            if mv in (tv, bv):
                chosen = tv
            elif tv == bv:
                chosen = mv
            elif key in ("position", "width", "height"):
                chosen = mv  # 옮기기·크기는 충돌로 보지 않고 내 것을 쓴다
            else:
                conflicts.append(_conflict(kind, iid, key, label, bv, mv, tv))
                chosen = tv
            if chosen is not MISSING:
                result[key] = copy.deepcopy(chosen)
        has_data = isinstance(t.get("data"), dict) or isinstance(m.get("data"), dict)
        out.append(_build(iid, result, has_data))
    return out


def _order(theirs: dict[str, Any], mine: dict[str, Any], base: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([*theirs, *mine, *base]))


def merge_graphs(base: dict[str, Any], mine: dict[str, Any], theirs: dict[str, Any]) -> MergeResult:
    conflicts: list[dict[str, Any]] = []
    b_nodes, m_nodes, t_nodes = (_by_id(g.get("nodes")) for g in (base, mine, theirs))
    nodes = _merge_items(
        "node", b_nodes, m_nodes, t_nodes, _order(t_nodes, m_nodes, b_nodes), conflicts
    )
    node_ids = {n["id"] for n in nodes}

    b_edges, m_edges, t_edges = (_by_id(g.get("edges")) for g in (base, mine, theirs))
    edges = _merge_items(
        "edge", b_edges, m_edges, t_edges, _order(t_edges, m_edges, b_edges), conflicts
    )
    dropped = 0
    kept: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for e in edges:
        if e.get("source") not in node_ids or e.get("target") not in node_ids:
            dropped += 1
            continue
        sig = tuple(e.get(k) for k in EDGE_KEYS)
        if sig in seen:  # 서로 다른 id로 같은 선을 이은 경우
            dropped += 1
            continue
        seen.add(sig)
        kept.append(e)

    b_notes, m_notes, t_notes = (_by_id(g.get("notes")) for g in (base, mine, theirs))
    notes = _merge_items(
        "note", b_notes, m_notes, t_notes, _order(t_notes, m_notes, b_notes), conflicts
    )

    variables: dict[str, Any] = {}
    bv_all, mv_all, tv_all = (dict(g.get("variables") or {}) for g in (base, mine, theirs))
    for key in dict.fromkeys([*tv_all, *mv_all]):
        bv, mv, tv = bv_all.get(key, MISSING), mv_all.get(key, MISSING), tv_all.get(key, MISSING)
        if mv in (tv, bv):
            chosen = tv
        elif tv == bv:
            chosen = mv
        else:
            conflicts.append(_conflict("variable", key, "*", key, bv, mv, tv))
            chosen = tv
        if chosen is not MISSING:
            variables[key] = copy.deepcopy(chosen)

    merged = copy.deepcopy(theirs)
    merged["nodes"] = nodes
    merged["edges"] = kept
    merged["variables"] = variables
    if notes or "notes" in theirs or "notes" in mine:
        merged["notes"] = notes
    return MergeResult(
        merged=merged,
        conflicts=conflicts,
        dropped_edges=dropped,
        auto_merged=not conflicts and mine != theirs,
    )
