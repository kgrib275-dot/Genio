"""빌더 에이전트 툴(설계서 §6-1). 에이전트는 이 툴로만 그래프를 바꾼다.

모든 변경은 앱 작업본(apps.draft_graph)에 바로 저장하고 PatchOp 목록으로 남긴다.
"""

import copy
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.builder.graph_summary import summarize
from api.deps import membership_role
from api.engine.describe import describe_run, describe_step
from api.engine.executor import load_graph
from api.llm.base import ToolDef
from api.market.service import installed_items, installed_keys, market_node_types
from api.models import (
    App,
    ConnectorCredential,
    ConnectorDefinition,
    Document,
    KnowledgeBase,
    MarketItem,
    Run,
    RunStep,
)
from api.schemas.graph import Graph, GraphEdge, GraphNode, Position, empty_graph
from api.services import apps as app_service
from api.services.projects import hidden_project_ids
from api.services.queue import enqueue_run
from nodes import NodeError, registry

TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        "get_graph",
        "현재 작업 중인 흐름 그래프를 가져온다. 노드에는 순번이 붙어 있어 '두 번째 노드'처럼 지칭된 노드를 찾을 수 있다.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolDef(
        "list_available_nodes",
        "쓸 수 있는 노드 타입, 설치된 서비스(커넥터)와 동작, 연결 정보(이름만), 지식베이스, 설치하지 않은 마켓 아이템 목록을 가져온다.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolDef(
        "add_node",
        "노드를 하나 추가한다. after를 주면 그 노드 바로 뒤에 붙이고 선을 이어 준다(after 다음에 있던 노드는 새 노드 뒤로 밀린다). after가 갈림길(condition·question_classifier)이면 handle에 분기 이름을, 실패 길이면 handle='fail'을 준다.",
        {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "노드 타입(list_available_nodes 참고)"},
                "data": {
                    "type": "object",
                    "description": "노드 설정. label(화면 이름)을 꼭 넣는다.",
                },
                "after": {"type": "string", "description": "이 노드 id 뒤에 붙인다"},
                "handle": {"type": "string", "description": "after가 condition일 때 분기 이름"},
            },
            "required": ["type", "data"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "update_node",
        "노드 설정을 고친다. data에 준 키만 바꾸고 나머지는 유지한다. 값을 null로 주면 그 키를 지운다.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}, "data": {"type": "object"}},
            "required": ["id", "data"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "remove_node",
        "노드와 그 노드에 이어진 선을 지운다. 앞뒤가 하나씩 이어져 있었다면 앞뒤를 다시 이어 준다.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "connect",
        "두 노드를 선으로 잇는다. source가 갈림길(condition·question_classifier)이면 handle(분기 이름)이, 실패 길이면 handle='fail'이 필요하다. 조건이 아닌 노드에서 이미 나가는 선이 있으면 새 선으로 바꾼다.",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "target": {"type": "string"},
                "handle": {"type": "string"},
            },
            "required": ["source", "target"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "ask_user",
        "필요한 정보가 빠졌을 때 사용자에게 묻는다. 고를 수 있는 답이 있으면 options로 준다. 이 툴을 부르면 이번 차례는 끝나고 사용자의 답을 기다린다.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "suggest_market_item",
        "필요한 서비스(커넥터)나 노드가 설치돼 있지 않을 때 마켓 아이템 설치를 제안한다. item_key를 알면 같이 준다. 이 툴을 부르면 이번 차례는 끝나고 사용자의 설치를 기다린다.",
        {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["connector", "node", "template", "prompt_pack"],
                },
                "reason": {"type": "string", "description": "왜 필요한지 쉬운 말로"},
                "item_key": {"type": "string"},
            },
            "required": ["type", "reason"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "run_test",
        "현재 흐름을 주어진 입력으로 테스트 실행하고 결과를 요약해 돌려준다. 실행 전에 검증을 먼저 통과해야 한다.",
        {
            "type": "object",
            "properties": {"input": {"type": "object", "description": "입력 노드 항목 키별 값"}},
            "required": ["input"],
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "get_run",
        "이 앱의 실행 결과를 읽는다. run_id를 주면 그 실행, 없으면 가장 최근 실행. 상태·오류·단계별 한 줄 설명(story)·단계별 짧은 결과를 돌려준다. '왜 실패했어?', '방금 결과 설명해 줘' 같은 요청이나 고쳐 달라는 요청에 쓴다.",
        {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "실행 id(없으면 최근)"}},
            "additionalProperties": False,
        },
    ),
    ToolDef(
        "validate",
        "흐름 그래프를 검증하고 노드별 오류를 돌려준다. 이 검증을 통과하기 전에는 완료라고 말하지 않는다.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
]
TOOL_SCHEMAS = {t.name: t.input_schema for t in TOOL_DEFS}
STOP_TOOLS = {"ask_user", "suggest_market_item"}
RUN_TEST_TIMEOUT = 120.0


@dataclass
class ToolOutcome:
    ok: bool
    result: dict[str, Any]
    summary: str
    ops: list[dict[str, Any]] = field(default_factory=list)
    event: tuple[str, dict[str, Any]] | None = None


class BuilderToolbox:
    def __init__(self, db: Session, app: App, user_id: str) -> None:
        self.db = db
        self.app = app
        self.user_id = user_id
        self.validated_ok = False

    # ----- 그래프 저장 -----
    def graph(self) -> Graph:
        return Graph.model_validate(self.app.draft_graph or empty_graph())

    def save(self, graph: Graph) -> None:
        self.app.draft_graph = graph.dump()
        self.db.commit()
        self.validated_ok = False

    # ----- 실행 -----
    def execute(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        schema = TOOL_SCHEMAS.get(name)
        if schema is None:
            return ToolOutcome(False, {"error": f"없는 툴: {name}"}, f"알 수 없는 툴 {name}")
        errors = list(Draft202012Validator(schema).iter_errors(args))
        if errors:
            return ToolOutcome(
                False,
                {
                    "error": "입력 형식이 올바르지 않아요",
                    "details": [e.message for e in errors[:5]],
                },
                "툴 입력 형식 오류",
            )
        handler = getattr(self, f"t_{name}")
        try:
            outcome: ToolOutcome = handler(**args)
        except ToolError as exc:
            return ToolOutcome(False, {"error": exc.message}, exc.message)
        return outcome

    # ----- 툴 구현 -----
    def t_get_graph(self) -> ToolOutcome:
        g = self.graph()
        return ToolOutcome(
            True,
            {"summary": summarize(g), "graph": g.dump()},
            f"노드 {len(g.nodes)}개, 선 {len(g.edges)}개",
        )

    def t_list_available_nodes(self) -> ToolOutcome:
        ws = self.app.workspace_id
        allowed = set(registry.types())
        market_types = market_node_types(self.db, ws)
        node_types = []
        for spec in registry.all():
            if spec.source == "market" and spec.type not in market_types:
                continue
            props = spec.input_schema.get("properties", {})
            node_types.append(
                {
                    "type": spec.type,
                    "label": spec.label,
                    "description": spec.description,
                    "data_fields": {
                        k: {
                            kk: vv
                            for kk, vv in v.items()
                            if kk in ("type", "title", "enum", "default")
                        }
                        for k, v in props.items()
                    },
                    "required": spec.input_schema.get("required", []),
                }
            )
        del allowed
        connectors = []
        for item in installed_items(self.db, ws, "connector"):
            connectors.append(
                {
                    "key": item.key,
                    "name": item.name,
                    "actions": [
                        {
                            "key": a.get("key"),
                            "label": a.get("label"),
                            "params": a.get("input_schema", {}),
                            "outputs": list(
                                (a.get("output_schema") or {}).get("properties", {}).keys()
                            ),
                        }
                        for a in item.manifest.get("actions", [])
                    ],
                }
            )
        creds = self.db.execute(
            select(ConnectorCredential.id, ConnectorCredential.name, ConnectorDefinition.key)
            .join(ConnectorDefinition, ConnectorDefinition.id == ConnectorCredential.definition_id)
            .where(ConnectorCredential.workspace_id == ws)
        ).all()
        kb_rows = self.db.execute(
            select(KnowledgeBase.id, KnowledgeBase.name, func.count(Document.id))
            .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
            .where(KnowledgeBase.workspace_id == ws)
            .group_by(KnowledgeBase.id, KnowledgeBase.name)
        ).all()
        role = membership_role(self.db, self.user_id, ws) or "member"
        hidden_kbs = set(
            self.db.scalars(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.workspace_id == ws,
                    KnowledgeBase.project_id.in_(
                        hidden_project_ids(self.db, ws, self.user_id, role)
                    ),
                )
            )
        )
        kb_rows = [k for k in kb_rows if k[0] not in hidden_kbs]
        installed = installed_keys(self.db, ws)
        market = [
            {"key": m.key, "type": m.type, "name": m.name, "summary": m.summary}
            for m in self.db.scalars(select(MarketItem).order_by(MarketItem.type, MarketItem.key))
            if m.key not in installed
        ]
        return ToolOutcome(
            True,
            {
                "node_types": node_types,
                "connectors": connectors,
                "credentials": [{"id": c[0], "name": c[1], "connector": c[2]} for c in creds],
                "knowledge_bases": [{"id": k[0], "name": k[1], "documents": k[2]} for k in kb_rows],
                "market_not_installed": market,
            },
            f"노드 {len(node_types)}종, 서비스 {len(connectors)}개, 연결 정보 {len(creds)}개, 지식베이스 {len(kb_rows)}개",
        )

    def _new_id(self, g: Graph) -> str:
        nums = [int(m.group(1)) for n in g.nodes if (m := re.fullmatch(r"n(\d+)", n.id))]
        return f"n{(max(nums) if nums else 0) + 1}"

    def _new_edge_id(self, g: Graph) -> str:
        nums = [int(m.group(1)) for e in g.edges if (m := re.fullmatch(r"e(\d+)", e.id))]
        return f"e{(max(nums) if nums else 0) + 1}"

    def _check_type(self, node_type: str) -> None:
        spec = registry.get(node_type)
        if spec is None:
            raise ToolError(
                f"'{node_type}' 노드 타입은 없어요. list_available_nodes로 쓸 수 있는 타입을 확인하세요."
            )
        if spec.source == "market" and node_type not in market_node_types(
            self.db, self.app.workspace_id
        ):
            raise ToolError(
                f"'{node_type}' 노드는 설치되지 않았어요. suggest_market_item으로 설치를 제안하세요."
            )

    def t_add_node(
        self, type: str, data: dict[str, Any], after: str | None = None, handle: str | None = None
    ) -> ToolOutcome:
        self._check_type(type)
        g = self.graph()
        ops: list[dict[str, Any]] = []
        if type == "input" and any(n.type == "input" for n in g.nodes):
            raise ToolError(
                "입력 노드는 하나만 둘 수 있어요. 기존 입력 노드를 update_node로 고치세요."
            )
        node_id = self._new_id(g)
        prev = g.node(after) if after else None
        if after and prev is None:
            raise ToolError(f"'{after}' 노드가 없어요. get_graph로 id를 확인하세요.")
        if prev is not None:
            branch_offset = 0.0
            cases = _exits(prev)
            if handle == "fail":
                if prev.data.get("_on_error") != "branch":
                    raise ToolError(
                        "'fail' 출구를 쓰려면 먼저 그 노드의 _on_error를 'branch'로 바꾸세요."
                    )
                branch_offset = 200.0
            elif cases is not None:
                if not handle:
                    raise ToolError(
                        f"갈림길 노드 뒤에 붙이려면 handle(분기 이름)이 필요해요: {', '.join(cases)}"
                    )
                if handle not in cases:
                    raise ToolError(f"'{handle}' 분기가 없어요. 가능한 분기: {', '.join(cases)}")
                branch_offset = (cases.index(handle) - (len(cases) - 1) / 2) * 160
            elif handle:
                raise ToolError(f"'{prev.id}' 노드에는 '{handle}' 출구가 없어요.")
            pos = Position(x=prev.position.x + 300, y=prev.position.y + branch_offset)
        else:
            max_x = max((n.position.x for n in g.nodes), default=-300)
            pos = Position(x=max_x + 300, y=0)
        node = GraphNode(id=node_id, type=type, position=pos, data=data)
        g.nodes.append(node)
        ops.append({"op": "add_node", "node": node.model_dump()})
        if prev is not None:
            old = [
                e
                for e in g.edges
                if e.source == prev.id and (e.source_handle or None) == (handle or None)
            ]
            for e in old:
                g.edges.remove(e)
                ops.append({"op": "remove_edge", "id": e.id})
            e1 = GraphEdge(
                id=self._new_edge_id(g), source=prev.id, target=node_id, source_handle=handle
            )
            g.edges.append(e1)
            ops.append({"op": "add_edge", "edge": e1.model_dump(by_alias=True, exclude_none=True)})
            if old and type not in ("output",):
                if type in ("condition", "question_classifier"):
                    pass  # 갈림길 노드 뒤 연결은 에이전트가 분기별로 정한다
                else:
                    e2 = GraphEdge(id=self._new_edge_id(g), source=node_id, target=old[0].target)
                    g.edges.append(e2)
                    ops.append(
                        {"op": "add_edge", "edge": e2.model_dump(by_alias=True, exclude_none=True)}
                    )
        self.save(g)
        label = data.get("label") or type
        return ToolOutcome(True, {"node_id": node_id}, f"'{label}' 노드 추가({node_id})", ops)

    def t_update_node(self, id: str, data: dict[str, Any]) -> ToolOutcome:
        g = self.graph()
        node = g.node(id)
        if node is None:
            raise ToolError(f"'{id}' 노드가 없어요. get_graph로 id를 확인하세요.")
        new_data = copy.deepcopy(node.data)
        for k, v in data.items():
            if v is None:
                new_data.pop(k, None)
            else:
                new_data[k] = v
        node.data = new_data
        self.save(g)
        changed = ", ".join(data.keys())
        return ToolOutcome(
            True,
            {"node_id": id, "data": new_data},
            f"'{new_data.get('label') or id}' 설정 변경: {changed}",
            [{"op": "update_node", "id": id, "data": new_data}],
        )

    def t_remove_node(self, id: str) -> ToolOutcome:
        g = self.graph()
        node = g.node(id)
        if node is None:
            raise ToolError(f"'{id}' 노드가 없어요.")
        ins = [e for e in g.edges if e.target == id]
        outs = [e for e in g.edges if e.source == id]
        ops: list[dict[str, Any]] = []
        for e in ins + outs:
            g.edges.remove(e)
            ops.append({"op": "remove_edge", "id": e.id})
        g.nodes.remove(node)
        ops.append({"op": "remove_node", "id": id})
        if len(ins) == 1 and len(outs) == 1 and _exits(node) is None:
            e = GraphEdge(
                id=self._new_edge_id(g),
                source=ins[0].source,
                target=outs[0].target,
                source_handle=ins[0].source_handle,
            )
            g.edges.append(e)
            ops.append({"op": "add_edge", "edge": e.model_dump(by_alias=True, exclude_none=True)})
        self.save(g)
        return ToolOutcome(
            True, {"removed": id}, f"'{node.data.get('label') or id}' 노드 삭제", ops
        )

    def t_connect(self, source: str, target: str, handle: str | None = None) -> ToolOutcome:
        g = self.graph()
        src, dst = g.node(source), g.node(target)
        if src is None or dst is None:
            raise ToolError("없는 노드를 이으려고 했어요. get_graph로 id를 확인하세요.")
        if source == target:
            raise ToolError("노드를 자기 자신과 이을 수 없어요.")
        ops: list[dict[str, Any]] = []
        cases = _exits(src)
        if handle == "fail":
            if src.data.get("_on_error") != "branch":
                raise ToolError(
                    "'fail' 출구를 쓰려면 먼저 그 노드의 _on_error를 'branch'로 바꾸세요."
                )
            old = [e for e in g.edges if e.source == source and e.source_handle == "fail"]
        elif cases is not None:
            if not handle or handle not in cases:
                raise ToolError(
                    f"갈림길 노드에서 이을 때는 분기 이름이 필요해요: {', '.join(cases)}"
                )
            old = [e for e in g.edges if e.source == source and e.source_handle == handle]
        else:
            handle = None
            old = [e for e in g.edges if e.source == source and not e.source_handle]
        for e in old:
            g.edges.remove(e)
            ops.append({"op": "remove_edge", "id": e.id})
        if _reachable(g, target, source):
            raise ToolError("이렇게 이으면 흐름이 되돌아가는 순환이 생겨요.")
        edge = GraphEdge(
            id=self._new_edge_id(g), source=source, target=target, source_handle=handle
        )
        g.edges.append(edge)
        ops.append({"op": "add_edge", "edge": edge.model_dump(by_alias=True, exclude_none=True)})
        self.save(g)
        via = f"({handle})" if handle else ""
        return ToolOutcome(True, {"edge_id": edge.id}, f"{source}{via} → {target} 연결", ops)

    def t_ask_user(self, question: str, options: list[str] | None = None) -> ToolOutcome:
        payload = {"question": question, "options": options or []}
        return ToolOutcome(
            True,
            {"status": "질문을 사용자에게 보여 줬어요. 답을 기다리세요."},
            f"질문: {question}",
            event=("ask_user", payload),
        )

    def t_suggest_market_item(
        self, type: str, reason: str, item_key: str | None = None
    ) -> ToolOutcome:
        installed = installed_keys(self.db, self.app.workspace_id)
        items = list(self.db.scalars(select(MarketItem).where(MarketItem.type == type)))
        chosen = next((i for i in items if i.key == item_key), None)
        if chosen is None:
            chosen = _best_match(items, f"{reason} {item_key or ''}")
        if chosen is None:
            options = ", ".join(f"{i.key}({i.name})" for i in items) or "없음"
            raise ToolError(
                f"설명에 맞는 마켓 아이템을 찾지 못했어요. item_key를 정해서 다시 부르세요. 이 종류의 아이템: {options}"
            )
        if chosen.key in installed:
            return ToolOutcome(
                True, {"already_installed": chosen.key}, f"'{chosen.name}'은(는) 이미 설치돼 있어요"
            )
        item = {
            "key": chosen.key,
            "type": chosen.type,
            "name": chosen.name,
            "summary": chosen.summary,
            "version": chosen.version,
            "publisher": chosen.publisher,
            "price": chosen.price,
            "tags": chosen.tags or [],
            "installs": chosen.installs,
            "installed": False,
        }
        return ToolOutcome(
            True,
            {
                "status": "설치 제안 카드를 보여 줬어요. 사용자의 설치를 기다리세요.",
                "item_key": chosen.key,
            },
            f"마켓 제안: {chosen.name}",
            event=("market_suggestion", {"item": item, "reason": reason}),
        )

    def t_get_run(self, run_id: str | None = None) -> ToolOutcome:
        q = select(Run).where(Run.app_id == self.app.id)
        if run_id:
            run = self.db.get(Run, run_id)
            if run is None or run.app_id != self.app.id:
                raise ToolError("이 앱의 실행 기록에서 그 실행을 찾지 못했어요")
        else:
            run = self.db.scalar(q.order_by(Run.created_at.desc()).limit(1))
            if run is None:
                return ToolOutcome(
                    True,
                    {"found": False, "message": "아직 실행한 적이 없어요"},
                    "실행 기록 없음",
                )
        try:
            graph = load_graph(self.db, run).dump()
        except NodeError:
            graph = self.graph().dump()
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        steps_out: list[dict[str, Any]] = []
        for s in self.db.scalars(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq)
        ):
            node = nodes.get(s.node_id)
            label = str(((node or {}).get("data") or {}).get("label") or s.node_id)
            d = {
                "status": s.status,
                "output": s.output,
                "logs": s.logs,
                "started_at": s.started_at,
                "finished_at": s.finished_at,
                "input": s.input,
            }
            steps_out.append(
                {
                    "node_id": s.node_id,
                    "label": label,
                    "type": (node or {}).get("type"),
                    "status": s.status,
                    "summary": describe_step(node, d, label),
                    # 비밀값이 섞일 수 있는 단계 설정(input)은 넘기지 않고 결과만 짧게
                    "output": _clip(s.output, 300),
                    "logs": (s.logs or "")[-300:],
                }
            )
        story = describe_run({"status": run.status}, steps_out)
        result = {
            "found": True,
            "run_id": run.id,
            "status": run.status,
            "trigger": run.trigger,
            "error": run.error,
            "input": _clip(run.input, 300),
            "output": _clip(run.output, 300),
            "story": story,
            "steps": steps_out,
            "uses_draft": run.version_id is None,
        }
        status_ko = {"succeeded": "성공", "failed": "실패", "waiting_approval": "승인 대기"}.get(
            run.status, run.status
        )
        return ToolOutcome(True, result, f"실행 결과 읽음({status_ko})")

    def t_validate(self) -> ToolOutcome:
        result = app_service.validate_for_app(self.db, self.app, self.graph().dump())
        self.validated_ok = result.valid
        errors = [e.model_dump() for e in result.errors]
        summary = "검증 통과" if result.valid else f"검증 오류 {len(errors)}개"
        return ToolOutcome(True, {"valid": result.valid, "errors": errors}, summary)

    def t_run_test(self, input: dict[str, Any]) -> ToolOutcome:
        graph = self.graph().dump()
        result = app_service.validate_for_app(self.db, self.app, graph)
        if not result.valid:
            return ToolOutcome(
                False,
                {
                    "error": "검증을 통과하지 못해 실행하지 않았어요",
                    "errors": [e.model_dump() for e in result.errors],
                },
                "검증 실패로 테스트 생략",
            )
        run = Run(
            app_id=self.app.id,
            trigger="test",
            status="queued",
            input=input,
            graph_snapshot=graph,
            created_by=self.user_id,
        )
        self.db.add(run)
        self.db.commit()
        enqueue_run(run.id)
        deadline = time.time() + RUN_TEST_TIMEOUT
        while True:
            self.db.expire_all()
            fresh = self.db.get(Run, run.id)
            if fresh is None or fresh.status in ("succeeded", "failed", "waiting_approval"):
                break
            if time.time() > deadline:
                break
            time.sleep(0.5)
        fresh = self.db.get(Run, run.id)
        if fresh is None:
            return ToolOutcome(False, {"error": "실행 기록이 사라졌어요"}, "테스트 실행 실패")
        steps = list(
            self.db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq))
        )
        step_summary = [
            {
                "node_id": s.node_id,
                "status": s.status,
                "output": _clip(s.output),
                "logs": s.logs[-300:],
            }
            for s in steps
        ]
        payload = {
            "run_id": run.id,
            "status": fresh.status,
            "output": fresh.output,
            "error": fresh.error,
        }
        status_ko = {
            "succeeded": "성공",
            "failed": "실패",
            "waiting_approval": "승인 대기",
            "running": "실행 중",
            "queued": "대기 중",
        }.get(fresh.status, fresh.status)
        return ToolOutcome(
            fresh.status != "failed",
            {**payload, "steps": step_summary},
            f"테스트 실행 {status_ko}",
            event=("test_result", payload),
        )


class ToolError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _exits(node: GraphNode) -> list[str] | None:
    """갈림길 노드의 분기 이름 목록(순서 유지). 갈림길이 아니면 None."""
    if node.type == "condition":
        return [str(c.get("id")) for c in node.data.get("cases", []) if c.get("id")] + [
            str(node.data.get("else") or "else")
        ]
    if node.type == "question_classifier":
        return [str(c.get("id")) for c in node.data.get("classes", []) if c.get("id")]
    if node.type == "approval" and node.data.get("branch"):
        return ["approved", "rejected"]  # 승인 / 반려(엔진 APPROVAL_HANDLES와 같음)
    return None


def _best_match(items: list[MarketItem], text: str) -> MarketItem | None:
    """설명 글에 아이템의 key·이름·태그가 들어 있는 만큼 점수를 매긴다.

    한국어는 조사가 붙으므로("구글시트에서") 단어 일치 대신 부분 문자열로 비교한다.
    아무것도 맞지 않으면 추측하지 않고 None을 돌려준다.
    """
    haystack = text.lower().replace(" ", "")
    best: MarketItem | None = None
    best_score = 0
    for item in items:
        terms = {item.key.lower(), *re.findall(r"[a-z0-9가-힣]{2,}", item.name.lower())}
        terms |= {t.lower().replace(" ", "") for t in (item.tags or []) if len(t) >= 2}
        score = sum(1 for t in terms if t and t in haystack)
        if score > best_score:
            best, best_score = item, score
    return best


def _reachable(g: Graph, start: str, goal: str) -> bool:
    stack, seen = [start], set()
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(e.target for e in g.edges if e.source == cur)
    return False


def _clip(value: Any, limit: int = 600) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return text[:limit] + "…"
