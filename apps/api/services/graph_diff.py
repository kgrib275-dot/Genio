"""v0.6 버전 비교: 두 흐름(버전·작업본) 사이에 더한·뺀·바뀐 단계와 선을 업무 말로 정리한다.

위치(position)만 바뀐 것은 '자리 옮김'으로만 센다(실행과 무관). 비밀값은 그래프에 없으므로
그대로 보여 줘도 되지만, 긴 값은 잘라서 보낸다.
"""

import json
from typing import Any

from api.schemas.graph import Graph, GraphEdge, GraphNode

MAX_VALUE = 300
# 화면에 보일 설정 이름(없으면 키 그대로)
FIELD_LABELS = {
    "label": "이름",
    "prompt": "AI에게 줄 지시",
    "system": "역할 지시",
    "template": "글 틀",
    "url": "주소",
    "method": "방식",
    "headers": "헤더",
    "body": "보낼 내용",
    "cases": "조건",
    "else": "그 밖의 길",
    "fields": "입력 칸",
    "model": "모델",
    "provider": "AI 연결",
    "message": "안내 문구",
    "branch": "승인/반려 갈래",
    "_retry": "다시 시도",
    "_on_error": "실패했을 때",
    "_default": "실패 시 기본값",
    "_timeout": "제한 시간",
    "code": "코드",
    "kb_id": "지식베이스",
    "query": "검색어",
    "classes": "분류",
    "parameters": "뽑을 값",
    "operation": "동작",
    "table_id": "데이터 표",
}


def _short(value: Any) -> str:
    if value is None:
        return "(없음)"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_VALUE else text[: MAX_VALUE - 1] + "…"


def _label(node: GraphNode) -> str:
    return str(node.data.get("label") or node.type)


def _edge_key(e: GraphEdge) -> tuple[str, str, str]:
    return (e.source, e.target, e.source_handle or "")


def _edge_text(e: GraphEdge, names: dict[str, str]) -> str:
    via = f" ({e.source_handle})" if e.source_handle else ""
    return f"{names.get(e.source, e.source)}{via} → {names.get(e.target, e.target)}"


def diff_graphs(old_raw: dict[str, Any], new_raw: dict[str, Any]) -> dict[str, Any]:
    old = Graph.model_validate(old_raw or {})
    new = Graph.model_validate(new_raw or {})
    old_nodes = {n.id: n for n in old.nodes}
    new_nodes = {n.id: n for n in new.nodes}
    names = {
        **{k: _label(v) for k, v in old_nodes.items()},
        **{k: _label(v) for k, v in new_nodes.items()},
    }

    added = [
        {"id": n.id, "type": n.type, "label": _label(n)} for n in new.nodes if n.id not in old_nodes
    ]
    removed = [
        {"id": n.id, "type": n.type, "label": _label(n)} for n in old.nodes if n.id not in new_nodes
    ]
    changed: list[dict[str, Any]] = []
    moved = 0
    for nid, after in new_nodes.items():
        before = old_nodes.get(nid)
        if before is None:
            continue
        fields: list[dict[str, Any]] = []
        if before.type != after.type:
            fields.append(
                {"key": "type", "name": "단계 종류", "before": before.type, "after": after.type}
            )
        if bool(before.disabled) != bool(after.disabled):
            fields.append(
                {
                    "key": "disabled",
                    "name": "켜기/끄기",
                    "before": "꺼짐" if before.disabled else "켜짐",
                    "after": "꺼짐" if after.disabled else "켜짐",
                }
            )
        for key in sorted(set(before.data) | set(after.data)):
            b, a = before.data.get(key), after.data.get(key)
            if b != a:
                fields.append(
                    {
                        "key": key,
                        "name": FIELD_LABELS.get(key, key),
                        "before": _short(b),
                        "after": _short(a),
                    }
                )
        if fields:
            changed.append(
                {"id": nid, "type": after.type, "label": _label(after), "fields": fields}
            )
        elif before.position != after.position:
            moved += 1

    old_edges = {_edge_key(e): e for e in old.edges}
    new_edges = {_edge_key(e): e for e in new.edges}
    edges_added = [_edge_text(e, names) for k, e in new_edges.items() if k not in old_edges]
    edges_removed = [_edge_text(e, names) for k, e in old_edges.items() if k not in new_edges]

    var_changes = [
        {"key": k, "before": _short(old.variables.get(k)), "after": _short(new.variables.get(k))}
        for k in sorted(set(old.variables) | set(new.variables))
        if old.variables.get(k) != new.variables.get(k)
    ]
    notes_before, notes_after = len(old.notes or []), len(new.notes or [])

    summary: list[str] = []
    if added:
        summary.append(f"단계 {len(added)}개 추가: {', '.join(a['label'] for a in added)}")
    if removed:
        summary.append(f"단계 {len(removed)}개 삭제: {', '.join(r['label'] for r in removed)}")
    if changed:
        summary.append(f"단계 {len(changed)}개 설정 변경: {', '.join(c['label'] for c in changed)}")
    if edges_added or edges_removed:
        summary.append(f"연결선 {len(edges_added)}개 추가, {len(edges_removed)}개 삭제")
    if var_changes:
        summary.append(f"흐름 값 {len(var_changes)}개 변경")
    if notes_before != notes_after:
        summary.append(f"메모 {notes_before}개 → {notes_after}개")
    if moved:
        summary.append(f"자리만 옮긴 단계 {moved}개")
    if not summary:
        summary.append("바뀐 내용이 없어요.")
    return {
        "same": not (added or removed or changed or edges_added or edges_removed or var_changes),
        "summary": summary,
        "nodes_added": added,
        "nodes_removed": removed,
        "nodes_changed": changed,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
        "variables_changed": var_changes,
        "moved": moved,
    }
