"""v0.2 단계 10종(docs/dify-gap.md §1). 기본 단계와 같은 NodeSpec 인터페이스."""

import json
from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}
LLM_PROPS: dict[str, Any] = {
    "provider": {"type": "string", "title": "AI 연결", "default": "default"},
    "model": {"type": "string", "title": "모델(비우면 기본값)"},
}
# iteration·loop 안에서 쓸 수 있는 하위 동작
CHILD_TYPES = [
    "llm",
    "template",
    "http",
    "code",
    "knowledge_search",
    "parameter_extractor",
    "connector",
]


def _llm(
    ctx: NodeContext, data: dict[str, Any], system: str, prompt: str, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = ctx.services.llm_complete(
        provider=str(data.get("provider") or "default"),
        model=data.get("model") or None,
        system=system,
        prompt=prompt,
        temperature=None,
        json_schema=schema,
    )
    usage = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
    }
    return result.data, usage


# ---------------- question_classifier ----------------
def _run_classifier(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    classes = [c for c in data.get("classes", []) if c.get("id")]
    if not classes:
        raise NodeError("분류를 하나 이상 만들어 주세요.")
    query = ctx.render(str(data.get("query", "")))
    if not query.strip():
        raise NodeError("분류할 글(query)이 비어 있어요.")
    ids = [str(c["id"]) for c in classes]
    lines = "\n".join(
        f"- {c['id']}: {c.get('name', '')} — {c.get('description', '')}" for c in classes
    )
    system = (
        "주어진 글을 아래 분류 중 하나로 정하세요. 반드시 분류 id 하나만 고르세요.\n"
        f"{lines}\n{ctx.render(str(data.get('instruction') or ''))}"
    )
    schema = {
        "type": "object",
        "properties": {"class_id": {"type": "string", "enum": ids}},
        "required": ["class_id"],
    }
    out, usage = _llm(ctx, data, system, query, schema)
    chosen = str((out or {}).get("class_id", ""))
    if chosen not in ids:
        ctx.log(f"AI가 고른 분류 '{chosen}'가 목록에 없어 첫 분류로 보냈어요.")
        chosen = ids[0]
    name = next((str(c.get("name", "")) for c in classes if str(c["id"]) == chosen), "")
    return NodeResult(output={"class_id": chosen, "class_name": name}, handle=chosen, usage=usage)


QUESTION_CLASSIFIER = NodeSpec(
    type="question_classifier",
    label="질문 분류",
    category="AI",
    description="AI가 글을 정해 둔 분류 중 하나로 나누고, 분류마다 다른 길로 보내요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            **LLM_PROPS,
            "query": {"type": "string", "title": "분류할 글", "default": "{{n1.message}}"},
            "classes": {
                "type": "array",
                "title": "분류",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "title": "분류 id(영문)"},
                        "name": {"type": "string", "title": "이름"},
                        "description": {"type": "string", "title": "설명"},
                    },
                    "required": ["id"],
                },
            },
            "instruction": {"type": "string", "title": "추가 지시(선택)"},
        },
        "required": ["query", "classes"],
    },
    output_schema={
        "type": "object",
        "properties": {"class_id": {"type": "string"}, "class_name": {"type": "string"}},
    },
    ui_schema={"query": {"ui:widget": "textarea"}, "instruction": {"ui:widget": "textarea"}},
    run=_run_classifier,
    outputs=lambda d: ["class_id", "class_name"],
)


# ---------------- parameter_extractor ----------------
_TYPES = {"string": "string", "number": "number", "boolean": "boolean", "array": "array"}


def _run_extractor(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    params = [p for p in data.get("parameters", []) if p.get("name")]
    if not params:
        raise NodeError("뽑아낼 항목을 하나 이상 정해 주세요.")
    query = ctx.render(str(data.get("query", "")))
    props = {
        str(p["name"]): {
            "type": _TYPES.get(str(p.get("type", "string")), "string"),
            "description": str(p.get("description", "")),
        }
        for p in params
    }
    required = [str(p["name"]) for p in params if p.get("required")]
    schema = {"type": "object", "properties": props, "required": required}
    system = "글에서 요청한 항목을 찾아 JSON으로만 답하세요. 없으면 null." + (
        "\n" + ctx.render(str(data.get("instruction"))) if data.get("instruction") else ""
    )
    out, usage = _llm(ctx, data, system, query, schema)
    result: dict[str, Any] = {name: None for name in props}
    if out is None:
        result.update({"__is_success": False, "__reason": "AI 응답을 읽지 못했어요."})
        return NodeResult(output=result, usage=usage)
    result.update({k: out.get(k) for k in props})
    missing = [k for k in required if result.get(k) in (None, "")]
    result["__is_success"] = not missing
    result["__reason"] = f"필수 항목을 찾지 못했어요: {', '.join(missing)}" if missing else ""
    return NodeResult(output=result, usage=usage)


PARAMETER_EXTRACTOR = NodeSpec(
    type="parameter_extractor",
    label="값 뽑아내기",
    category="AI",
    description="AI가 글에서 이름·날짜·금액 같은 값을 골라 항목별로 정리해요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            **LLM_PROPS,
            "query": {"type": "string", "title": "대상 글", "default": "{{n1.message}}"},
            "parameters": {
                "type": "array",
                "title": "뽑아낼 항목",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "title": "이름(영문)"},
                        "type": {
                            "type": "string",
                            "title": "형식",
                            "enum": list(_TYPES),
                            "default": "string",
                        },
                        "description": {"type": "string", "title": "설명"},
                        "required": {"type": "boolean", "title": "필수", "default": False},
                    },
                    "required": ["name"],
                },
            },
            "instruction": {"type": "string", "title": "추가 지시(선택)"},
        },
        "required": ["query", "parameters"],
    },
    output_schema={"type": "object", "description": "항목별 값 + __is_success, __reason"},
    ui_schema={"query": {"ui:widget": "textarea"}, "instruction": {"ui:widget": "textarea"}},
    run=_run_extractor,
    outputs=lambda d: (
        [str(p.get("name")) for p in d.get("parameters", []) if p.get("name")]
        + ["__is_success", "__reason"]
    ),
)


# ---------------- template ----------------
TEMPLATE = NodeSpec(
    type="template",
    label="글 틀",
    category="기본",
    description="여러 단계의 값을 하나의 글로 엮어요. Jinja2 문법(반복·조건)을 쓸 수 있어요.",
    input_schema={
        "type": "object",
        "properties": {"label": LABEL, "template": {"type": "string", "title": "글 틀"}},
        "required": ["template"],
    },
    output_schema={"type": "object", "properties": {"output": {"type": "string"}}},
    ui_schema={"template": {"ui:widget": "textarea"}},
    run=lambda data, ctx: NodeResult(output={"output": ctx.render(str(data.get("template", "")))}),
    outputs=lambda d: ["output"],
)


# ---------------- variable_aggregator ----------------
def _run_aggregator(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    for v in data.get("variables", []):
        value = ctx.render_value(v)
        if value not in (None, "", [], {}):
            return NodeResult(output={"output": value})
    return NodeResult(output={"output": None})


VARIABLE_AGGREGATOR = NodeSpec(
    type="variable_aggregator",
    label="값 모으기",
    category="흐름",
    description="갈라졌던 길의 결과 중 실제로 실행된 쪽의 값 하나를 골라 이어 줘요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "variables": {
                "type": "array",
                "title": "후보 값(위에서부터)",
                "items": {"type": "string"},
            },
        },
        "required": ["variables"],
    },
    output_schema={"type": "object", "properties": {"output": {}}},
    ui_schema={},
    run=_run_aggregator,
    outputs=lambda d: ["output"],
)


# ---------------- list_operator ----------------
def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [line for line in value.splitlines() if line.strip()]
        if isinstance(parsed, list):
            return parsed
    if value is None:
        return []
    raise NodeError("목록(배열) 값이 필요해요.")


def _pick(item: Any, key: str | None) -> Any:
    if key and isinstance(item, dict):
        return item.get(key)
    return item


def _match(v: Any, op: str, target: Any) -> bool:
    if op == "contains":
        return str(target) in str(v)
    if op == "not_contains":
        return str(target) not in str(v)
    if op == "eq":
        return str(v) == str(target)
    if op == "ne":
        return str(v) != str(target)
    if op in ("gt", "lt"):
        try:
            a, b = float(v), float(target)
        except (TypeError, ValueError):
            return False
        return a > b if op == "gt" else a < b
    if op == "is_empty":
        return v in (None, "", [], {})
    if op == "not_empty":
        return v not in (None, "", [], {})
    return True


def _run_list(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    items = _as_list(ctx.render_value(data.get("input")))
    f = data.get("filter") or {}
    if f.get("operator"):
        target = ctx.render_value(f.get("value"))
        items = [i for i in items if _match(_pick(i, f.get("key")), str(f["operator"]), target)]
    srt = data.get("sort") or {}
    if srt.get("enabled"):
        items = sorted(
            items, key=lambda i: str(_pick(i, srt.get("key"))), reverse=srt.get("order") == "desc"
        )
    offset = int(data.get("offset") or 0)
    limit = data.get("limit")
    items = items[offset:]
    if limit:
        items = items[: int(limit)]
    return NodeResult(
        output={
            "result": items,
            "first": items[0] if items else None,
            "last": items[-1] if items else None,
            "count": len(items),
        }
    )


LIST_OPERATOR = NodeSpec(
    type="list_operator",
    label="목록 다루기",
    category="흐름",
    description="목록에서 조건에 맞는 것만 거르고, 정렬하고, 앞에서 몇 개만 남겨요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "input": {"type": "string", "title": "대상 목록", "default": "{{n2.results}}"},
            "filter": {
                "type": "object",
                "title": "거르기",
                "properties": {
                    "key": {"type": "string", "title": "항목 키(객체일 때)"},
                    "operator": {
                        "type": "string",
                        "title": "조건",
                        "enum": [
                            "",
                            "contains",
                            "not_contains",
                            "eq",
                            "ne",
                            "gt",
                            "lt",
                            "is_empty",
                            "not_empty",
                        ],
                        "default": "",
                    },
                    "value": {"type": "string", "title": "비교 값"},
                },
            },
            "sort": {
                "type": "object",
                "title": "정렬",
                "properties": {
                    "enabled": {"type": "boolean", "title": "정렬하기", "default": False},
                    "key": {"type": "string", "title": "기준 키"},
                    "order": {
                        "type": "string",
                        "title": "순서",
                        "enum": ["asc", "desc"],
                        "default": "asc",
                    },
                },
            },
            "offset": {"type": "integer", "title": "건너뛸 개수", "default": 0, "minimum": 0},
            "limit": {"type": "integer", "title": "남길 개수(비우면 전부)", "minimum": 1},
        },
        "required": ["input"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "array"},
            "first": {},
            "last": {},
            "count": {"type": "integer"},
        },
    },
    ui_schema={},
    run=_run_list,
    outputs=lambda d: ["result", "first", "last", "count"],
)


# ---------------- iteration / loop ----------------
def _child(data: dict[str, Any], reg: NodeRegistry) -> tuple[NodeSpec, dict[str, Any]]:
    op = data.get("operation") or {}
    node_type = str(op.get("type") or "")
    if node_type not in CHILD_TYPES:
        raise NodeError(f"반복 안에서 쓸 동작을 골라 주세요({', '.join(CHILD_TYPES)}).")
    spec = reg.get(node_type)
    if spec is None:
        raise NodeError(f"'{node_type}' 동작을 찾지 못했어요.")
    return spec, dict(op.get("data") or {})


def make_iteration(reg: NodeRegistry) -> NodeSpec:
    def run(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
        items = _as_list(ctx.render_value(data.get("items")))
        limit = min(int(data.get("max_items") or 50), 100)
        if len(items) > limit:
            ctx.log(f"항목이 {len(items)}개라 앞의 {limit}개만 처리해요.")
            items = items[:limit]
        spec, op_data = _child(data, reg)
        key = str(data.get("output_key") or "")
        results: list[Any] = []
        for i, item in enumerate(items):
            res = spec.run(op_data, ctx.with_scope({"item": item, "index": i}))
            results.append(res.output.get(key) if key else res.output)
        return NodeResult(output={"results": results, "count": len(results)})

    return NodeSpec(
        type="iteration",
        label="항목마다 반복",
        category="흐름",
        description="목록의 항목 하나하나에 같은 동작(AI 응답, 웹 요청 등)을 해서 결과 목록을 만들어요. 동작 안에서 {{item}}, {{index}}를 써요.",
        input_schema={
            "type": "object",
            "properties": {
                "label": LABEL,
                "items": {"type": "string", "title": "대상 목록", "default": "{{n2.result}}"},
                "operation": {
                    "type": "object",
                    "title": "항목마다 할 동작",
                    "properties": {
                        "type": {
                            "type": "string",
                            "title": "동작 종류",
                            "enum": CHILD_TYPES,
                            "default": "llm",
                        },
                        "data": {"type": "object", "title": "동작 설정"},
                    },
                    "required": ["type"],
                },
                "output_key": {"type": "string", "title": "결과에서 꺼낼 값(예: text)"},
                "max_items": {
                    "type": "integer",
                    "title": "최대 항목 수",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["items", "operation"],
        },
        output_schema={
            "type": "object",
            "properties": {"results": {"type": "array"}, "count": {"type": "integer"}},
        },
        ui_schema={"operation": {"data": {"ui:widget": "json"}}},
        run=run,
        outputs=lambda d: ["results", "count"],
    )


def make_loop(reg: NodeRegistry) -> NodeSpec:
    def run(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
        spec, op_data = _child(data, reg)
        key = str(data.get("output_key") or "")
        max_n = max(1, min(int(data.get("max_iterations") or 5), 20))
        last: Any = ctx.render_value(data.get("initial"))
        results: list[Any] = []
        stop = str(data.get("break_when") or "").strip()
        for i in range(max_n):
            child = ctx.with_scope({"loop": {"index": i, "last": last}})
            res = spec.run(op_data, child)
            last = res.output.get(key) if key else res.output
            results.append(last)
            if stop:
                check = ctx.with_scope({"loop": {"index": i, "last": last}})
                try:
                    if check.evaluate(stop):
                        ctx.log(f"{i + 1}번째에 멈춤 조건을 만족했어요.")
                        break
                except Exception as exc:
                    raise NodeError(f"멈춤 조건을 계산하지 못했어요: {exc}") from exc
        return NodeResult(output={"results": results, "last": last, "iterations": len(results)})

    return NodeSpec(
        type="loop",
        label="되풀이",
        category="흐름",
        description="앞 결과를 이어받아 같은 동작을 여러 번 해요(초안 다듬기 등). {{loop.last}}, {{loop.index}}를 써요.",
        input_schema={
            "type": "object",
            "properties": {
                "label": LABEL,
                "initial": {"type": "string", "title": "처음 값"},
                "operation": {
                    "type": "object",
                    "title": "되풀이할 동작",
                    "properties": {
                        "type": {
                            "type": "string",
                            "title": "동작 종류",
                            "enum": CHILD_TYPES,
                            "default": "llm",
                        },
                        "data": {"type": "object", "title": "동작 설정"},
                    },
                    "required": ["type"],
                },
                "output_key": {"type": "string", "title": "결과에서 꺼낼 값(예: text)"},
                "break_when": {
                    "type": "string",
                    "title": "멈춤 조건(예: contains({{loop.last}}, '완료'))",
                },
                "max_iterations": {
                    "type": "integer",
                    "title": "최대 횟수",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["operation"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "array"},
                "last": {},
                "iterations": {"type": "integer"},
            },
        },
        ui_schema={"operation": {"data": {"ui:widget": "json"}}},
        run=run,
        outputs=lambda d: ["results", "last", "iterations"],
    )


# ---------------- document_extractor ----------------
def _run_doc(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    value = ctx.render_value(data.get("file"))
    ids = [str(v) for v in (value if isinstance(value, list) else [value]) if v]
    if not ids:
        raise NodeError(
            "읽을 파일이 없어요. 입력 단계에 파일 항목을 두고 {{n1.파일키}}를 넣어 주세요."
        )
    texts, names = [], []
    for fid in ids:
        name, mime, content = ctx.services.read_file(file_id=fid)
        texts.append(ctx.services.extract_text(filename=name, mime=mime, content=content))
        names.append(name)
    limit = int(data.get("max_chars") or 20000)
    text = "\n\n".join(texts)
    if len(text) > limit:
        ctx.log(f"글이 길어 앞의 {limit}자만 넘겨요.")
        text = text[:limit]
    return NodeResult(output={"text": text, "filenames": names})


DOCUMENT_EXTRACTOR = NodeSpec(
    type="document_extractor",
    label="파일 읽기",
    category="기본",
    description="올린 PDF·텍스트 파일에서 글을 꺼내요. 다음 AI 단계에 {{단계.text}}로 넘겨요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "file": {"type": "string", "title": "파일", "default": "{{n1.file}}"},
            "max_chars": {
                "type": "integer",
                "title": "최대 글자 수",
                "default": 20000,
                "minimum": 1000,
            },
        },
        "required": ["file"],
    },
    output_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "filenames": {"type": "array"}},
    },
    ui_schema={},
    run=_run_doc,
    outputs=lambda d: ["text", "filenames"],
)


# ---------------- variable_assigner ----------------
def _run_assigner(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    updates: dict[str, Any] = {}
    for a in data.get("assignments", []):
        name = str(a.get("variable") or "").strip()
        if not name:
            continue
        mode = str(a.get("mode") or "overwrite")
        current = ctx.render_value("{{conv." + name + "}}")
        if mode == "clear":
            new: Any = None
        elif mode == "append":
            base = (
                current
                if isinstance(current, list)
                else ([] if current in (None, "") else [current])
            )
            new = [*base, ctx.render_value(a.get("value"))]
        else:
            new = ctx.render_value(a.get("value"))
        updates[name] = new
    return NodeResult(output={"__conv_set": updates, **updates})


VARIABLE_ASSIGNER = NodeSpec(
    type="variable_assigner",
    label="대화 값 저장",
    category="흐름",
    description="챗봇이 대화 내내 기억할 값(이름, 선택한 메뉴 등)을 저장해요. 다른 단계에서 {{conv.이름}}으로 써요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "assignments": {
                "type": "array",
                "title": "저장할 값",
                "items": {
                    "type": "object",
                    "properties": {
                        "variable": {"type": "string", "title": "값 이름(영문)"},
                        "value": {"type": "string", "title": "값"},
                        "mode": {
                            "type": "string",
                            "title": "방식",
                            "enum": ["overwrite", "append", "clear"],
                            "default": "overwrite",
                        },
                    },
                    "required": ["variable"],
                },
            },
        },
        "required": ["assignments"],
    },
    output_schema={"type": "object", "description": "저장한 값"},
    ui_schema={},
    run=_run_assigner,
    outputs=None,
)


# ---------------- agent ----------------
def _run_agent(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    query = ctx.render(str(data.get("query", "")))
    if not query.strip():
        raise NodeError("에이전트에게 줄 요청(query)이 비어 있어요.")
    tools = [t for t in (data.get("tools") or []) if isinstance(t, dict) and t.get("type")]
    out = ctx.services.run_agent(
        provider=str(data.get("provider") or "default"),
        model=data.get("model") or None,
        instruction=ctx.render(str(data.get("instruction") or "")),
        query=query,
        tools=tools,
        max_iterations=max(1, min(int(data.get("max_iterations") or 5), 10)),
    )
    for call in out.get("tool_calls", []):
        ctx.log(f"도구 사용: {call.get('name')} → {str(call.get('summary', ''))[:120]}")
    return NodeResult(output={"text": out.get("text", ""), "tool_calls": out.get("tool_calls", [])})


AGENT = NodeSpec(
    type="agent",
    label="에이전트",
    category="AI",
    description="AI가 목표를 이루기 위해 필요한 도구(서비스 연결, 웹 페이지 읽기, 지식 검색, 다른 앱)를 스스로 골라 써요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            **LLM_PROPS,
            "instruction": {"type": "string", "title": "역할·규칙"},
            "query": {"type": "string", "title": "요청", "default": "{{n1.message}}"},
            "tools": {
                "type": "array",
                "title": "쓸 수 있는 도구",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "title": "종류",
                            "enum": ["web", "knowledge", "connector", "app"],
                        },
                        "kb_id": {"type": "string", "title": "지식베이스 id(knowledge)"},
                        "connector": {"type": "string", "title": "서비스(connector)"},
                        "action": {"type": "string", "title": "동작(connector)"},
                        "credential_id": {"type": "string", "title": "연결 정보(connector)"},
                        "app_id": {"type": "string", "title": "앱 id(app)"},
                        "description": {"type": "string", "title": "언제 쓰는지 설명"},
                    },
                    "required": ["type"],
                },
            },
            "max_iterations": {
                "type": "integer",
                "title": "최대 도구 사용 횟수",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "tool_calls": {"type": "array"}},
    },
    ui_schema={"instruction": {"ui:widget": "textarea"}, "query": {"ui:widget": "textarea"}},
    run=_run_agent,
    outputs=lambda d: ["text", "tool_calls"],
)


def register_v02(reg: NodeRegistry) -> None:
    for spec in [
        QUESTION_CLASSIFIER,
        PARAMETER_EXTRACTOR,
        TEMPLATE,
        VARIABLE_AGGREGATOR,
        LIST_OPERATOR,
        make_iteration(reg),
        make_loop(reg),
        DOCUMENT_EXTRACTOR,
        VARIABLE_ASSIGNER,
        AGENT,
    ]:
        if reg.get(spec.type) is None:
            reg.register(spec)
