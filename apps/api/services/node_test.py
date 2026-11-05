"""v0.8 단계 하나만 시험: 캔버스에서 고른 단계를 샘플 값으로 혼자 실행해 본다.

- 앞 단계의 결과는 요청으로 받은 값을 쓰고, 안 보내면 가장 최근에 성공한 실행의 값으로 채운다.
- 실행 기록은 남기지 않는다. 대신 실제로 바깥에 영향을 주는 단계(연결·외부 호출·데이터 표 쓰기 등)는
  화면이 먼저 확인을 받도록 warn 문장을 함께 돌려준다.
- 사람을 기다리는 단계(승인·질문·배정)는 혼자 시험할 수 없다.
"""

import copy
import re
from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.engine.describe import describe_step
from api.engine.executor import _limits_message, run_node_once
from api.engine.templating import iter_refs
from api.engine.validator import _UI_KEYS, RESERVED_SCOPES
from api.models import App, Run, RunStep
from api.schemas.graph import Graph

PERSON_TYPES = {"approval", "ask_person", "assign_task"}
# 값을 직접 고칠 수 있는 범위(나머지 vars·env는 서버가 알아서 채운다)
EDITABLE_SCOPES = ("input", "conv")
SKIP_SCOPES = {"vars", "env", "item", "index", "loop"}
READ_ONLY_TABLE_OPS = {"get", "find", "list", "count", "query", "search"}


def _graph_of(app: App, data: dict[str, Any] | None, node_id: str) -> tuple[Graph, Any]:
    raw = copy.deepcopy(app.draft_graph or {})
    try:
        graph = Graph.model_validate(raw)
    except Exception:
        raise AppError(
            422, "흐름 형식이 올바르지 않아요.", "빌더에서 흐름을 고친 뒤 다시 시험하세요."
        ) from None
    node = graph.node(node_id)
    if node is None:
        raise AppError(
            404,
            "그 단계를 찾을 수 없어요.",
            "캔버스에서 단계를 다시 고르세요(저장되지 않은 단계는 먼저 저장하세요).",
        )
    if data is not None:
        node.data = dict(data)  # 아직 저장하지 않은 설정 패널의 값으로 시험한다
    return graph, node


def _warn(node_type: str, data: dict[str, Any]) -> tuple[str | None, bool]:
    """(확인 문장, 바깥에 영향을 주는지). 영향이 있으면 화면이 실행 전에 한 번 더 묻는다."""
    if node_type == "connector":
        return "연결된 서비스(메일·메신저 등)로 실제 요청이 나가요.", True
    if node_type == "http" and str(data.get("method") or "GET").upper() not in ("GET", "HEAD"):
        return "외부 주소로 실제 요청이 나가요(보내기·바꾸기 방식).", True
    if node_type == "data_table" and str(data.get("operation") or "") not in READ_ONLY_TABLE_OPS:
        return "데이터 표에 실제로 값이 저장·삭제돼요.", True
    if node_type == "run_app":
        return "다른 앱이 실제로 한 번 실행돼요.", True
    if node_type == "agent":
        return "에이전트가 도구를 실제로 써서 비용이 들거나 바깥에 영향을 줄 수 있어요.", True
    if node_type in ("llm", "question_classifier", "parameter_extractor", "knowledge_search"):
        return "AI를 실제로 한 번 불러서 비용이 조금 들어요.", False
    return None, False


def _latest_success(db: Session, app_id: str) -> tuple[Run | None, dict[str, dict[str, Any]]]:
    run = db.scalar(
        select(Run)
        .where(Run.app_id == app_id, Run.status == "succeeded")
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    if run is None:
        return None, {}
    outs: dict[str, dict[str, Any]] = {}
    for st in db.scalars(
        select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq, RunStep.started_at)
    ):
        if st.status in ("succeeded", "skipped") and isinstance(st.output, dict):
            outs[st.node_id] = st.output
    return run, outs


def _kind(v: Any) -> str:
    if v is None:
        return "empty"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return "json"


_BLOCK_RE = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)
_TOKEN_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _refs(node_data: dict[str, Any], scopes: set[str]) -> list[tuple[str, str]]:
    """단계 설정이 쓰는 (앞 단계 또는 입력, 값 이름) 목록.

    `{{n1.name}}`처럼 값만 있는 참조(엔진이 쓰는 iter_refs)에 더해, `{{ 100 // n1.qty }}`나
    `{% if n1.vip %}`처럼 식 안에 들어 있는 참조도 찾는다.
    """
    data = {k: v for k, v in node_data.items() if k not in _UI_KEYS}
    seen: dict[tuple[str, str], None] = {}
    for ref in iter_refs(data):
        seen.setdefault(ref, None)
    for text in _strings(data):
        for block in _BLOCK_RE.finditer(text):
            for tok in _TOKEN_RE.finditer(block.group(1) or block.group(2) or ""):
                if tok.group(1) in scopes:
                    seen.setdefault((tok.group(1), tok.group(2)), None)
    return list(seen)


def test_inputs(db: Session, app: App, node_id: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """이 단계가 쓰는 앞 단계 값 목록과, 최근 성공한 실행에서 채운 값."""
    graph, node = _graph_of(app, data, node_id)
    reason = None
    if node.type in PERSON_TYPES:
        reason = "사람 단계는 단독으로 시험할 수 없어요."
    elif node.disabled:
        reason = "꺼 둔 단계예요. 먼저 켜 주세요."
    run, outs = _latest_success(db, app.id)
    run_input = {
        k: v for k, v in dict((run.input if run else {}) or {}).items() if not k.startswith("__")
    }
    conv = dict(((run.output or {}).get("conv") if run and run.output else None) or {})
    warn, risky = _warn(node.type, node.data)
    groups: dict[str, dict[str, Any]] = {}
    labels = {n.id: str(n.data.get("label") or n.type) for n in graph.nodes}
    for scope, field in _refs(node.data, {n.id for n in graph.nodes} | set(EDITABLE_SCOPES)):
        if scope in SKIP_SCOPES or not field:
            continue
        if scope not in RESERVED_SCOPES and graph.node(scope) is None:
            continue
        if scope == "input":
            source: dict[str, Any] = run_input
        elif scope == "conv":
            source = conv
        else:
            source = outs.get(scope, {})
        value = source.get(field)
        g = groups.setdefault(
            scope,
            {
                "scope": scope,
                "label": {"input": "입력 값", "conv": "대화 값"}.get(
                    scope, labels.get(scope, scope)
                ),
                "editable": True,
                "fields": [],
            },
        )
        if all(f["field"] != field for f in g["fields"]):
            g["fields"].append(
                {
                    "field": field,
                    "path": f"{{{{{scope}.{field}}}}}",
                    "value": value,
                    "kind": _kind(value),
                    "from_last_run": field in source,
                }
            )
    return {
        "node_id": node.id,
        "type": node.type,
        "label": labels.get(node.id, node.id),
        "testable": reason is None,
        "reason": reason,
        "warn": warn,
        "risky": risky,
        "last_run_id": run.id if run else None,
        "groups": list(groups.values()),
    }


def run_test(
    db: Session,
    app: App,
    node_id: str,
    values: dict[str, dict[str, Any]] | None,
    data: dict[str, Any] | None,
) -> dict[str, Any]:
    graph, node = _graph_of(app, data, node_id)
    if node.type in PERSON_TYPES:
        raise AppError(
            422, "사람 단계는 단독으로 시험할 수 없어요.", "흐름 전체를 테스트 실행해서 확인하세요."
        )
    if node.disabled:
        raise AppError(422, "꺼 둔 단계는 시험할 수 없어요.", "단계를 켠 뒤 다시 시험하세요.")
    blocked = _limits_message(db, app)
    if blocked:
        raise AppError(429, blocked, "관리 > 사용량에서 한도를 확인하세요.")
    run, outs = _latest_success(db, app.id)
    run_input = {
        k: v for k, v in dict((run.input if run else {}) or {}).items() if not k.startswith("__")
    }
    conv = dict(((run.output or {}).get("conv") if run and run.output else None) or {})
    if values is None:
        scoped = outs
    else:
        scoped = {k: dict(v) for k, v in values.items() if isinstance(v, dict)}
        run_input = dict(scoped.pop("input", run_input) or {})
        conv = dict(scoped.pop("conv", conv) or {})
    scoped.pop("input", None)
    scoped.pop("conv", None)
    res = run_node_once(db, app, graph, node_id, values=scoped, run_input=run_input, conv=conv)
    label = str(node.data.get("label") or node.type)
    tokens = {
        "input_tokens": sum(int(u[1]) for u in res.get("usage", [])),
        "output_tokens": sum(int(u[2]) for u in res.get("usage", [])),
    }
    base: dict[str, Any] = {
        "node_id": node_id,
        "ms": res["ms"],
        "logs": res["logs"],
        "tokens": tokens,
    }
    if res["kind"] == "ok":
        out = dict(res["value"].output)
        out.pop("__conv_set", None)
        step = {"status": "succeeded", "output": out, "logs": "\n".join(res["logs"])}
        return {
            **base,
            "ok": True,
            "output": out,
            "handle": res["value"].handle,
            "summary": describe_step(
                {"id": node_id, "type": node.type, "data": node.data}, step, label
            ),
            "error": None,
        }
    if res["kind"] == "error":
        return {
            **base,
            "ok": False,
            "output": None,
            "handle": None,
            "summary": "",
            "error": {
                "message": str(res["value"]),
                "hint": "아래 앞 단계 값이나 이 단계의 설정을 확인한 뒤 다시 시험하세요.",
            },
        }
    return {
        **base,
        "ok": False,
        "output": None,
        "handle": None,
        "summary": "",
        "error": {
            "message": "시험하는 중 예상하지 못한 문제가 생겼어요.",
            "hint": "잠시 뒤 다시 시험하고, 계속되면 앱을 만든 사람에게 알려 주세요.",
        },
    }
