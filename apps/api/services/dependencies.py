"""연결 관계 지도: 어떤 앱이 어떤 연결 정보·지식베이스·데이터 표·스킬·다른 앱을 쓰는지.

바꾸거나 지우기 전에 '이걸 쓰는 앱이 어디인지' 보는 용도다. 앱의 작업본(draft_graph)에서 단계 설정의 id 칸을
훑어 모으고(비밀값은 읽지 않는다), 이름은 이 워크스페이스의 자원 표에서 찾는다.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import App, ConnectorCredential, DataTable, KnowledgeBase, Workspace

# 단계 설정의 칸 이름 → 자원 종류
KEY_KIND = {
    "credential_id": "credential",
    "tool_set": "credential",
    "kb_id": "kb",
    "table_id": "table",
    "app_id": "app",
}
LIST_KEY_KIND = {"skill_ids": "skill"}
KIND_LABEL = {
    "credential": "연결 정보",
    "kb": "지식베이스",
    "table": "데이터 표",
    "app": "다른 앱",
    "skill": "스킬",
}


def _refs(value: Any, out: set[tuple[str, str]], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            kind = KEY_KIND.get(str(k))
            if kind and isinstance(v, str) and v.strip() and "{{" not in v:
                out.add((kind, v.strip()))
            elif str(k) in LIST_KEY_KIND and isinstance(v, list):
                for x in v:
                    if isinstance(x, str) and x.strip():
                        out.add((LIST_KEY_KIND[str(k)], x.strip()))
            else:
                _refs(v, out, depth + 1)
    elif isinstance(value, list):
        for x in value[:200]:
            _refs(x, out, depth + 1)


def graph_refs(graph: dict[str, Any] | None) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for node in (graph or {}).get("nodes", []) or []:
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict):
            _refs(data, out)
    return out


def build(db: Session, workspace_id: str) -> dict[str, Any]:
    apps = list(db.scalars(select(App).where(App.workspace_id == workspace_id)))
    names: dict[tuple[str, str], str] = {}
    for cid, n in db.execute(
        select(ConnectorCredential.id, ConnectorCredential.name).where(
            ConnectorCredential.workspace_id == workspace_id
        )
    ):
        names[("credential", cid)] = n
    for kid, n in db.execute(
        select(KnowledgeBase.id, KnowledgeBase.name).where(
            KnowledgeBase.workspace_id == workspace_id
        )
    ):
        names[("kb", kid)] = n
    for tid, n in db.execute(
        select(DataTable.id, DataTable.name).where(DataTable.workspace_id == workspace_id)
    ):
        names[("table", tid)] = n
    for a in apps:
        names[("app", a.id)] = a.name
    ws = db.get(Workspace, workspace_id)
    for s in (ws.settings or {}).get("skills", []) if ws else []:
        names[("skill", str(s.get("id")))] = str(s.get("name"))

    used_by: dict[tuple[str, str], list[dict[str, str]]] = {k: [] for k in names}
    app_rows: list[dict[str, Any]] = []
    for a in apps:
        uses = []
        for kind, rid in sorted(graph_refs(a.draft_graph)):
            key = (kind, rid)
            if key == ("app", a.id):
                continue
            known = key in names
            uses.append(
                {
                    "kind": kind,
                    "id": rid,
                    "name": names.get(key, "(없어진 자원)"),
                    "missing": not known,
                }
            )
            if known:
                used_by[key].append({"app_id": a.id, "app_name": a.name})
        app_rows.append({"app_id": a.id, "name": a.name, "uses": uses})
    resources = [
        {
            "kind": kind,
            "kind_label": KIND_LABEL[kind],
            "id": rid,
            "name": names[(kind, rid)],
            "used_by": users,
            "unused": not users and kind in ("credential", "kb", "table", "skill"),
        }
        for (kind, rid), users in used_by.items()
        if kind != "app" or users
    ]
    resources.sort(key=lambda r: (r["kind"], str(r["name"]).lower()))
    return {
        "resources": resources,
        "apps": sorted(app_rows, key=lambda r: str(r["name"]).lower()),
        "unused_count": sum(1 for r in resources if r["unused"]),
        "missing_count": sum(1 for a in app_rows for u in a["uses"] if u["missing"]),
    }
