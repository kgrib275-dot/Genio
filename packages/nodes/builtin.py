"""기본 단계 9종(설계서 §4). 1단계 6종 + knowledge_search, connector, approval."""

from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec, quote_block

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
        if f.get("type") == "number" and value == "":
            value = None  # 비워 둔 숫자 칸(필수가 아니면 없음으로)
        if value is not None and f.get("type") == "number":
            try:
                num = float(value)
            except (TypeError, ValueError) as exc:
                raise NodeError(f"'{key}' 값은 숫자여야 해요.") from exc
            # 2 → "2.0"처럼 보이지 않게 정수는 정수로 둔다
            value = int(num) if num.is_integer() and abs(num) < 2**53 else num
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
        # 챗 앱: 앱 기능의 기억 창(memory.window)만큼 이전 대화를 붙인다.
        # 이전 대화는 지시가 아니라 자료라는 것이 드러나게 구분해 넣는다(프롬프트 인젝션 기본 방어).
        prompt = f"{quote_block('이전 대화', history)}\n\n{prompt}"
    if not prompt.strip():
        raise NodeError("프롬프트가 비어 있어요. 단계 설정에서 프롬프트를 채워 주세요.")
    temp = data.get("temperature")
    kwargs: dict[str, Any] = {
        "provider": str(data.get("provider") or "default"),
        "model": data.get("model") or None,
        "system": system,
        "prompt": prompt,
        "temperature": float(temp) if temp is not None else None,
        "json_schema": schema,
        "stream": schema is None,
    }
    images = _image_refs(data.get("images"), ctx)
    if images:
        kwargs["images"] = images
        ctx.log(f"이미지 {len(images)}장을 함께 보내요.")
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


def _image_refs(raw: Any, ctx: NodeContext) -> list[str]:
    """이미지 칸(v0.6 비전): 값 끌어오기를 풀고, 파일 여러 개(목록)는 펼친다. 빈 값은 뺀다."""
    if raw in (None, "", []):
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        value = ctx.render_value(item) if isinstance(item, str) else item
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, dict):  # 파일 정보 묶음({id, filename, ...})도 받아 준다
                v = v.get("id") or v.get("url") or ""
            if v not in (None, "") and str(v).strip():
                out.append(str(v).strip())
    return out


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
            images={
                "type": "array",
                "title": "함께 볼 이미지(파일·주소, 최대 4장)",
                "description": "입력 단계의 파일 항목({{n1.photo}})이나 공개 이미지 주소. 이미지를 볼 수 있는 모델이 필요해요.",
                "items": {"type": "string"},
                "maxItems": 4,
            },
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
MAX_PAGES = 10


def _dig(value: Any, path: str) -> Any:
    """'data.next' 처럼 점으로 이은 경로의 값을 꺼낸다."""
    cur = value
    for part in [x for x in path.split(".") if x]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _items_of(body: Any, items_path: str) -> list[Any] | None:
    found = _dig(body, items_path) if items_path else body
    return found if isinstance(found, list) else None


def _with_param(url: str, param: str, value: Any) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != param]
    query.append((param, str(value)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _run_http(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    method = str(data.get("method") or "GET").upper()
    url = ctx.render(str(data.get("url", "")))
    headers = {str(k): ctx.render(str(v)) for k, v in (data.get("headers") or {}).items()}
    body = ctx.render_value(data.get("body"))
    raw_auth = data.get("auth")
    auth: dict[str, Any] | None = raw_auth if isinstance(raw_auth, dict) else None
    if auth and str(auth.get("type") or "none") == "none":
        auth = None
    raw_pag = data.get("pagination")
    pag: dict[str, Any] = raw_pag if isinstance(raw_pag, dict) else {}
    kind = str(pag.get("type") or "none")
    if kind == "none":
        res = ctx.services.http_request(
            method=method, url=url, headers=headers, body=body, auth=auth
        )
        return NodeResult(output=res)
    # 여러 쪽(페이지)을 차례로 받아 목록을 합친다(최대 10쪽)
    max_pages = max(1, min(int(pag.get("max_pages") or 3), MAX_PAGES))
    items_path = str(pag.get("items_path") or "")
    merged: list[Any] = []
    pages = 0
    status = 0
    next_url: str | None = url
    page_no = int(pag.get("start") or 1)
    while next_url and pages < max_pages:
        res = ctx.services.http_request(
            method=method, url=next_url, headers=headers, body=body, auth=auth
        )
        pages += 1
        status = int(res.get("status") or 0)
        items = _items_of(res.get("body"), items_path)
        if items is None:
            raise NodeError(
                "페이지 넘김 설정의 '목록 위치'에서 목록을 찾지 못했어요. 응답 모양을 확인해 주세요."
            )
        merged.extend(items)
        if kind == "next_url":
            nxt = _dig(res.get("body"), str(pag.get("path") or "next"))
            next_url = str(nxt) if isinstance(nxt, str) and nxt.strip() else None
        else:  # page: 쪽 번호를 하나씩 늘린다. 빈 쪽이 오면 끝
            if not items:
                break
            page_no += 1
            next_url = _with_param(url, str(pag.get("param") or "page"), page_no)
    ctx.log(f"{pages}쪽을 받아 {len(merged)}개 항목을 모았어요.")
    return NodeResult(output={"status": status, "body": merged, "pages": pages})


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
            auth={
                "type": "object",
                "title": "인증",
                "description": "비밀값은 '연결 정보'에서 골라요. 값은 화면·기록에 나오지 않아요.",
                "properties": {
                    "type": {
                        "type": "string",
                        "title": "방식",
                        "enum": ["none", "bearer", "basic", "header"],
                        "enumNames": ["없음", "토큰(Bearer)", "아이디·비밀번호", "헤더에 키 넣기"],
                        "default": "none",
                    },
                    "credential_id": {"type": "string", "title": "연결 정보"},
                    "header_name": {
                        "type": "string",
                        "title": "헤더 이름",
                        "default": "X-API-Key",
                    },
                },
            },
            pagination={
                "type": "object",
                "title": "여러 쪽 받기",
                "properties": {
                    "type": {
                        "type": "string",
                        "title": "방식",
                        "enum": ["none", "next_url", "page"],
                        "enumNames": ["한 번만", "응답의 다음 주소 따라가기", "쪽 번호 늘리기"],
                        "default": "none",
                    },
                    "items_path": {"type": "string", "title": "목록 위치(예: data.items)"},
                    "path": {"type": "string", "title": "다음 주소 위치(예: next)"},
                    "param": {"type": "string", "title": "쪽 번호 이름", "default": "page"},
                    "max_pages": {
                        "type": "integer",
                        "title": "최대 쪽 수",
                        "minimum": 1,
                        "maximum": MAX_PAGES,
                        "default": 3,
                    },
                },
            },
        ),
        "required": ["url"],
    },
    output_schema={
        "type": "object",
        "properties": {"status": {"type": "integer"}, "body": {}, "pages": {"type": "integer"}},
    },
    ui_schema={
        "body": {"ui:widget": "json"},
        "headers": {"ui:widget": "json"},
        "auth": {"credential_id": {"ui:widget": "credential"}},
    },
    run=_run_http,
    outputs=lambda d: ["status", "body", "pages"],
    retries=2,
)


# ---------------- code ----------------
def _run_code(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    code = str(data.get("code", ""))
    if not code.strip():
        raise NodeError("코드가 비어 있어요.")
    inputs = {str(k): ctx.render_value(v) for k, v in (data.get("inputs") or {}).items()}
    language = str(data.get("language") or "python")
    if language not in ("python", "javascript"):
        raise NodeError("코드 언어는 파이썬이나 자바스크립트만 쓸 수 있어요.")
    result = ctx.services.run_code(code=code, inputs=inputs, language=language)
    return NodeResult(output=result)


CODE = NodeSpec(
    type="code",
    label="코드",
    category="고급",
    description=(
        "파이썬이나 자바스크립트 코드로 값을 가공해요. inputs로 값을 받고 result에 결과(객체)를 넣어요. "
        "파일·인터넷에는 접근할 수 없어요."
    ),
    input_schema={
        "type": "object",
        "properties": _props(
            language={
                "type": "string",
                "title": "언어",
                "enum": ["python", "javascript"],
                "enumNames": ["파이썬", "자바스크립트"],
                "default": "python",
            },
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
    output_schema={"type": "object", "description": "result 값의 내용"},
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
    description="올려 둔 문서에서 질문과 가까운 내용을 찾아요. 결과를 AI 응답 단계에 넘겨 답하게 해요.",
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
        raise NodeError("연결 정보가 선택되지 않았어요. 단계 설정에서 연결 정보를 골라 주세요.")
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
def notify_config(data: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    """사람에게 보낼 알림 설정(이메일·슬랙). 받는 사람 칸은 값 끌어오기를 쓸 수 있다."""
    got = data.get("notify")
    raw: dict[str, Any] = got if isinstance(got, dict) else {}
    out: dict[str, Any] = {}
    e = raw.get("email")
    email: dict[str, Any] = e if isinstance(e, dict) else {}
    if email.get("credential_id") and email.get("to"):
        out["email"] = {
            "credential_id": str(email["credential_id"]),
            "to": [x.strip() for x in ctx.render(str(email["to"])).split(",") if x.strip()][:20],
        }
    sl = raw.get("slack")
    slack: dict[str, Any] = sl if isinstance(sl, dict) else {}
    if slack.get("credential_id") and slack.get("channel"):
        out["slack"] = {
            "credential_id": str(slack["credential_id"]),
            "channel": ctx.render(str(slack["channel"])),
        }
    return out


NOTIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "알림 보내기",
    "description": "요청을 이메일·슬랙으로 보내요. 받은 사람은 링크에서 바로 처리할 수 있어요.",
    "properties": {
        "email": {
            "type": "object",
            "title": "이메일",
            "properties": {
                "credential_id": {"type": "string", "title": "보내는 메일 연결 정보"},
                "to": {"type": "string", "title": "받는 사람(쉼표로 여러 명)"},
            },
        },
        "slack": {
            "type": "object",
            "title": "슬랙",
            "properties": {
                "credential_id": {"type": "string", "title": "슬랙 연결 정보"},
                "channel": {"type": "string", "title": "채널(예: #approvals)"},
            },
        },
    },
}
NOTIFY_UI: dict[str, Any] = {
    "email": {"credential_id": {"ui:widget": "credential"}},
    "slack": {"credential_id": {"ui:widget": "credential"}},
}


ON_TIMEOUT = ["none", "reject", "approve", "escalate", "continue", "branch"]
ON_TIMEOUT_NAMES = [
    "아무것도 안 함(계속 기다림)",
    "자동 반려(멈춤)",
    "자동 승인",
    "다른 사람·역할에게 올리기",
    "정해 둔 값으로 계속",
    "'시간 초과' 길로 보내기",
]
TIMEOUT_PROPS: dict[str, Any] = {
    "due_hours": {"type": "number", "title": "기한(시간)", "minimum": 0},
    "on_timeout": {
        "type": "string",
        "title": "기한이 지나면",
        "enum": ON_TIMEOUT,
        "enumNames": ON_TIMEOUT_NAMES,
        "default": "none",
    },
    "timeout_escalate_to": {
        "type": "string",
        "title": "올릴 곳(역할 이름 또는 사용자 id)",
        "description": "owner·admin·builder·operator 중 하나, 또는 사용자 id",
    },
    "timeout_default": {
        "type": "object",
        "title": "정해 둔 값(받을 칸 이름: 값)",
        "description": "'정해 둔 값으로 계속'을 골랐을 때 대신 쓰는 답",
    },
    "remind_before_hours": {
        "type": "number",
        "title": "기한 몇 시간 전에 다시 알릴까요",
        "minimum": 0,
    },
}
TIMEOUT_UI: dict[str, Any] = {"timeout_default": {"ui:widget": "json"}}


def _hours(v: Any) -> float | None:
    try:
        n = float(v or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def timing(data: dict[str, Any]) -> dict[str, Any]:
    """사람 단계의 기한·시간 초과 설정(작업함이 쓴다). 안 정했으면 모두 비어 있다."""
    mode = str(data.get("on_timeout") or "none")
    default = data.get("timeout_default")
    return {
        "due_hours": _hours(data.get("due_hours")),
        "on_timeout": mode if mode in ON_TIMEOUT else "none",
        "timeout_escalate_to": str(data.get("timeout_escalate_to") or "").strip() or None,
        "timeout_default": default if isinstance(default, dict) else {},
        "remind_before_hours": _hours(data.get("remind_before_hours")),
    }


def _run_approval(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    message = ctx.render(str(data.get("message") or "승인이 필요해요."))
    return NodeResult(
        output={},
        wait_approval={
            "kind": "approval",
            "message": message,
            "approver_roles": data.get("approver_roles") or [],
            **timing(data),
            "notify": notify_config(data, ctx),
        },
    )


APPROVAL = NodeSpec(
    type="approval",
    label="사람 승인",
    category="흐름",
    description=(
        "사람이 승인할 때까지 흐름을 멈춰요. 이메일·슬랙으로 요청을 보내고, 받은 사람은 링크에서 "
        "승인·반려와 한마디를 남겨요. 승인·반려 길을 따로 이을 수 있어요."
    ),
    input_schema={
        "type": "object",
        "properties": _props(
            message={"type": "string", "title": "승인 요청 문구"},
            approver_roles={
                "type": "array",
                "title": "승인할 수 있는 역할",
                "items": {"type": "string", "enum": ["owner", "admin", "builder", "operator"]},
            },
            branch={
                "type": "boolean",
                "title": "승인·반려 길 나누기",
                "description": "켜면 '승인'·'반려' 출구가 생겨요. 끄면 반려될 때 흐름이 멈춰요.",
                "default": True,
            },
            notify=NOTIFY_SCHEMA,
            **TIMEOUT_PROPS,
        ),
        "required": ["message"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "comment": {"type": "string"},
            "approver": {"type": "string"},
            "timed_out": {"type": "boolean"},
        },
    },
    ui_schema={"message": {"ui:widget": "textarea"}, "notify": NOTIFY_UI, **TIMEOUT_UI},
    run=_run_approval,
    outputs=lambda d: ["approved", "comment", "approver", "timed_out"],
)


BUILTIN_SPECS = [INPUT, LLM, CONDITION, HTTP, CODE, OUTPUT, KNOWLEDGE_SEARCH, CONNECTOR, APPROVAL]


def register_builtins(reg: NodeRegistry) -> None:
    for spec in BUILTIN_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
