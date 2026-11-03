"""기본 노드 9종(설계서 §4). 1단계 6종 + knowledge_search, connector, approval."""

from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}


def _props(**props: Any) -> dict[str, Any]:
    return {"label": LABEL, **props}


# ---------------- input ----------------
def _run_input(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    out: dict[str, Any] = {}
    missing = []
    for f in data.get("fields", []):
        key = f.get("key")
        if not key:
            continue
        value = ctx.run_input.get(key)
        if (value is None or value == "") and f.get("required"):
            missing.append(f.get("label") or key)
        if value is not None and f.get("type") == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise NodeError(f"'{key}' 값은 숫자여야 해요.") from exc
        out[key] = value
    if missing:
        raise NodeError(f"필수 입력이 비어 있어요: {', '.join(missing)}")
    return NodeResult(output=out)


INPUT = NodeSpec(
    type="input",
    label="입력",
    category="기본",
    description="흐름이 받을 입력 항목을 정해요. 흐름마다 하나만 있어야 해요.",
    input_schema={
        "type": "object",
        "properties": _props(
            fields={
                "type": "array",
                "title": "입력 항목",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "title": "키",
                            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                        },
                        "label": {"type": "string", "title": "표시 이름"},
                        "type": {
                            "type": "string",
                            "title": "형식",
                            "enum": ["text", "number", "boolean", "file"],
                            "default": "text",
                        },
                        "required": {"type": "boolean", "title": "필수", "default": True},
                    },
                    "required": ["key"],
                },
            }
        ),
        "required": ["fields"],
    },
    output_schema={"type": "object", "description": "입력 항목 키별 값"},
    ui_schema={},
    run=_run_input,
    outputs=lambda d: [f.get("key") for f in d.get("fields", []) if f.get("key")],
)


# ---------------- llm ----------------
def _run_llm(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    schema = data.get("output_schema") or None
    if schema is not None and not isinstance(schema, dict):
        raise NodeError("출력 형식(output_schema)은 JSON 객체여야 해요.")
    system = ctx.render(str(data.get("system", "")))
    prompt = ctx.render(str(data.get("prompt", "")))
    history = str(ctx.run_input.get("history") or "")
    if data.get("memory") and history.strip():
        # 챗 앱: 앱 기능의 기억 창(memory.window)만큼 이전 대화를 붙인다
        prompt = f"이전 대화:\n{history}\n\n{prompt}"
    if not prompt.strip():
        raise NodeError("프롬프트가 비어 있어요. 노드 설정에서 프롬프트를 채워 주세요.")
    temp = data.get("temperature")
    kwargs: dict[str, Any] = {
        "provider": str(data.get("provider") or "default"),
        "model": data.get("model") or None,
        "system": system,
        "prompt": prompt,
        "temperature": float(temp) if temp is not None else None,
        "json_schema": schema,
    }
    result = ctx.services.llm_complete(**kwargs)
    usage: dict[str, Any] = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
    if schema is not None and result.data is None:
        # 설계서 §5: JSON 파싱 실패 시 1회 재요청
        ctx.log("응답을 JSON으로 읽지 못해 한 번 더 요청해요.")
        result = ctx.services.llm_complete(**kwargs)
        usage["input_tokens"] += result.input_tokens
        usage["output_tokens"] += result.output_tokens
        if result.data is None:
            raise NodeError(
                "AI 응답을 정해진 형식으로 읽지 못했어요. 프롬프트나 출력 형식을 단순하게 바꿔 보세요."
            )
    output: dict[str, Any] = {"text": result.text}
    if result.data is not None:
        output.update(result.data)
    usage["model"] = result.model
    return NodeResult(output=output, usage=usage)


def _llm_outputs(data: dict[str, Any]) -> list[str]:
    schema = data.get("output_schema") or {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return ["text", *props.keys()]


LLM = NodeSpec(
    type="llm",
    label="AI 응답",
    category="AI",
    description="AI 모델에 프롬프트를 보내 답을 받아요. 출력 형식을 정하면 항목별로 나눠 받아요.",
    input_schema={
        "type": "object",
        "properties": _props(
            provider={"type": "string", "title": "AI 연결", "default": "default"},
            model={"type": "string", "title": "모델(비우면 기본값)"},
            temperature={"type": "number", "title": "창의성(0~1)", "minimum": 0, "maximum": 2},
            system={"type": "string", "title": "역할 지시"},
            prompt={"type": "string", "title": "프롬프트"},
            output_schema={"type": "object", "title": "출력 형식(JSON Schema)"},
            memory={"type": "boolean", "title": "이전 대화 기억(챗 앱)", "default": False},
        ),
        "required": ["prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "description": "text + output_schema의 항목",
    },
    ui_schema={
        "system": {"ui:widget": "textarea"},
        "prompt": {"ui:widget": "textarea"},
        "output_schema": {"ui:widget": "json"},
    },
    run=_run_llm,
    outputs=_llm_outputs,
)


# ---------------- condition ----------------
def _run_condition(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    for case in data.get("cases", []):
        when = str(case.get("when", "")).strip()
        if not when:
            continue
        try:
            ok = bool(ctx.evaluate(when))
        except Exception as exc:
            raise NodeError(f"조건식 '{when}'을(를) 계산하지 못했어요: {exc}") from exc
        ctx.log(f"{case.get('id')}: {when} → {ok}")
        if ok:
            return NodeResult(output={"matched": case.get("id")}, handle=str(case.get("id")))
    else_id = str(data.get("else") or "else")
    return NodeResult(output={"matched": else_id}, handle=else_id)


CONDITION = NodeSpec(
    type="condition",
    label="조건 분기",
    category="흐름",
    description="조건에 따라 다음 단계를 고르는 갈림길이에요. 위에서부터 처음 맞는 조건으로 가요.",
    input_schema={
        "type": "object",
        "properties": _props(
            cases={
                "type": "array",
                "title": "조건",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "title": "분기 이름"},
                        "when": {"type": "string", "title": "조건식"},
                    },
                    "required": ["id", "when"],
                },
            },
            **{"else": {"type": "string", "title": "나머지 분기 이름", "default": "else"}},
        ),
        "required": ["cases"],
    },
    output_schema={"type": "object", "properties": {"matched": {"type": "string"}}},
    ui_schema={},
    run=_run_condition,
    outputs=lambda d: ["matched"],
)


# ---------------- http ----------------
def _run_http(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    method = str(data.get("method") or "GET").upper()
    url = ctx.render(str(data.get("url", "")))
    headers = {str(k): ctx.render(str(v)) for k, v in (data.get("headers") or {}).items()}
    body = ctx.render_value(data.get("body"))
    res = ctx.services.http_request(method=method, url=url, headers=headers, body=body)
    return NodeResult(output=res)


HTTP = NodeSpec(
    type="http",
    label="웹 요청",
    category="연동",
    description="다른 서비스의 주소로 요청을 보내고 응답을 받아요. 사내망·내부 주소는 막혀 있어요.",
    input_schema={
        "type": "object",
        "properties": _props(
            method={
                "type": "string",
                "title": "방식",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            url={"type": "string", "title": "주소"},
            headers={
                "type": "object",
                "title": "헤더",
                "additionalProperties": {"type": "string"},
            },
            body={"title": "본문"},
        ),
        "required": ["url"],
    },
    output_schema={
        "type": "object",
        "properties": {"status": {"type": "integer"}, "body": {}},
    },
    ui_schema={"body": {"ui:widget": "json"}, "headers": {"ui:widget": "json"}},
    run=_run_http,
    outputs=lambda d: ["status", "body"],
    retries=2,
)


# ---------------- code ----------------
def _run_code(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    code = str(data.get("code", ""))
    if not code.strip():
        raise NodeError("코드가 비어 있어요.")
    inputs = {str(k): ctx.render_value(v) for k, v in (data.get("inputs") or {}).items()}
    result = ctx.services.run_code(code=code, inputs=inputs)
    return NodeResult(output=result)


CODE = NodeSpec(
    type="code",
    label="코드",
    category="고급",
    description="파이썬 코드로 값을 가공해요. inputs로 값을 받고 result 변수에 결과(dict)를 넣어요.",
    input_schema={
        "type": "object",
        "properties": _props(
            inputs={
                "type": "object",
                "title": "입력값",
                "additionalProperties": {"type": "string"},
            },
            code={
                "type": "string",
                "title": "코드",
                "default": "result = {'value': inputs.get('value')}",
            },
        ),
        "required": ["code"],
    },
    output_schema={"type": "object", "description": "result 변수의 내용"},
    ui_schema={"code": {"ui:widget": "code"}, "inputs": {"ui:widget": "json"}},
    run=_run_code,
    outputs=None,
)


# ---------------- output ----------------
def _run_output(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    return NodeResult(output={"text": ctx.render(str(data.get("template", "")))})


OUTPUT = NodeSpec(
    type="output",
    label="결과",
    category="기본",
    description="흐름의 최종 결과 문장을 만들어요. 챗봇이면 이 문장이 답변이 돼요.",
    input_schema={
        "type": "object",
        "properties": _props(template={"type": "string", "title": "결과 문장"}),
        "required": ["template"],
    },
    output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    ui_schema={"template": {"ui:widget": "textarea"}},
    run=_run_output,
    outputs=lambda d: ["text"],
)


# ---------------- knowledge_search ----------------
def _run_kb(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    kb_id = str(data.get("kb_id") or "")
    if not kb_id:
        raise NodeError("검색할 지식베이스를 골라 주세요.")
    query = ctx.render(str(data.get("query", "")))
    top_k = int(data.get("top_k") or 4)
    mf = ctx.render_value(data.get("metadata_filter") or {})
    thr = data.get("score_threshold")
    results = ctx.services.kb_search(
        kb_id=kb_id,
        query=query,
        top_k=top_k,
        method=str(data.get("method") or "") or None,
        score_threshold=float(thr) if thr not in (None, "") else None,
        metadata_filter=mf if isinstance(mf, dict) and mf else None,
    )
    context = "\n\n".join(f"[{i + 1}] {r.get('content', '')}" for i, r in enumerate(results))
    return NodeResult(output={"results": results, "context": context})


KNOWLEDGE_SEARCH = NodeSpec(
    type="knowledge_search",
    label="지식 검색",
    category="AI",
    description="올려 둔 문서에서 질문과 가까운 내용을 찾아요. 결과를 AI 응답 노드에 넘겨 답하게 해요.",
    input_schema={
        "type": "object",
        "properties": _props(
            kb_id={"type": "string", "title": "지식베이스"},
            query={"type": "string", "title": "검색어"},
            method={
                "type": "string",
                "title": "검색 방식(비우면 지식베이스 설정)",
                "enum": ["", "vector", "keyword", "hybrid"],
                "default": "",
            },
            score_threshold={
                "type": "number",
                "title": "최소 점수(0~1)",
                "minimum": 0,
                "maximum": 1,
            },
            metadata_filter={
                "type": "object",
                "title": "메타데이터 필터(키: 값)",
                "additionalProperties": {"type": "string"},
            },
            top_k={
                "type": "integer",
                "title": "가져올 개수",
                "default": 4,
                "minimum": 1,
                "maximum": 20,
            },
        ),
        "required": ["kb_id", "query"],
    },
    output_schema={
        "type": "object",
        "properties": {"results": {"type": "array"}, "context": {"type": "string"}},
    },
    ui_schema={"kb_id": {"ui:widget": "kb"}, "metadata_filter": {"ui:widget": "json"}},
    run=_run_kb,
    outputs=lambda d: ["results", "context"],
)


# ---------------- connector ----------------
def _run_connector(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    connector = str(data.get("connector") or "")
    action = str(data.get("action") or "")
    credential_id = str(data.get("credential_id") or "")
    if not (connector and action):
        raise NodeError("연결할 서비스와 동작을 골라 주세요.")
    if not credential_id:
        raise NodeError("연결 정보가 선택되지 않았어요. 노드 설정에서 연결 정보를 골라 주세요.")
    params = ctx.render_value(data.get("params") or {})
    if not isinstance(params, dict):
        raise NodeError("동작 설정 값은 항목:값 형태여야 해요.")
    out = ctx.services.run_connector(
        connector=connector, credential_id=credential_id, action=action, params=params
    )
    return NodeResult(output=out)


CONNECTOR = NodeSpec(
    type="connector",
    label="서비스 연결",
    category="연동",
    description="슬랙·메일·구글시트 같은 서비스에 동작을 실행해요. 마켓에서 설치한 서비스만 쓸 수 있어요.",
    input_schema={
        "type": "object",
        "properties": _props(
            connector={"type": "string", "title": "서비스"},
            credential_id={"type": "string", "title": "연결 정보"},
            action={"type": "string", "title": "동작"},
            params={"type": "object", "title": "동작 설정"},
        ),
        "required": ["connector", "action"],
    },
    output_schema={"type": "object", "description": "동작별 출력"},
    ui_schema={
        "connector": {"ui:widget": "connector"},
        "credential_id": {"ui:widget": "credential"},
        "action": {"ui:widget": "connectorAction"},
        "params": {"ui:widget": "json"},
    },
    run=_run_connector,
    outputs=None,
    retries=2,
)


# ---------------- approval ----------------
def _run_approval(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    message = ctx.render(str(data.get("message") or "승인이 필요해요."))
    return NodeResult(
        output={},
        wait_approval={"message": message, "approver_roles": data.get("approver_roles") or []},
    )


APPROVAL = NodeSpec(
    type="approval",
    label="사람 승인",
    category="흐름",
    description="사람이 승인할 때까지 흐름을 멈춰요. 승인하면 다음 단계로, 거절하면 멈춰요.",
    input_schema={
        "type": "object",
        "properties": _props(
            message={"type": "string", "title": "승인 요청 문구"},
            approver_roles={
                "type": "array",
                "title": "승인할 수 있는 역할",
                "items": {"type": "string", "enum": ["owner", "admin", "builder", "operator"]},
            },
        ),
        "required": ["message"],
    },
    output_schema={
        "type": "object",
        "properties": {"approved": {"type": "boolean"}, "comment": {"type": "string"}},
    },
    ui_schema={"message": {"ui:widget": "textarea"}},
    run=_run_approval,
    outputs=lambda d: ["approved", "comment", "approver"],
)


BUILTIN_SPECS = [INPUT, LLM, CONDITION, HTTP, CODE, OUTPUT, KNOWLEDGE_SEARCH, CONNECTOR, APPROVAL]


def register_builtins(reg: NodeRegistry) -> None:
    for spec in BUILTIN_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
