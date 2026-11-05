"""v0.8 외부 도구 단계: MCP 도구 호출(mcp_tool), API 도구 호출(api_tool, OpenAPI로 가져온 도구).

둘 다 '연결 정보'를 고르고 도구를 골라 값을 넣는다. 비밀값은 엔진이 연결 정보에서만 꺼낸다.
"""

from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}


# ---------------- MCP 도구 ----------------
def _run_mcp_tool(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    cred = str(data.get("credential_id") or "").strip()
    tool = str(data.get("tool") or "").strip()
    if not cred:
        raise NodeError("외부 도구 서버(MCP 연결 정보)를 골라 주세요.")
    if not tool:
        raise NodeError("부를 도구를 골라 주세요.")
    args = ctx.render_value(data.get("arguments") if data.get("arguments") is not None else {})
    if not isinstance(args, dict):
        raise NodeError("도구에 줄 값은 {이름: 값} 모양이어야 해요. '넘길 값' 칸을 확인하세요.")
    res = ctx.services.mcp_call(credential_id=cred, tool=tool, arguments=args)
    if res.get("is_error"):
        ctx.log(f"외부 도구 '{tool}'가 오류를 알려 줬어요.")
        if data.get("fail_on_tool_error"):
            raise NodeError(
                f"외부 도구 '{tool}'가 오류를 알려 줬어요: {str(res.get('text', ''))[:200]}. 넘긴 값을 확인하세요."
            )
    else:
        ctx.log(f"외부 도구 '{tool}' 호출을 마쳤어요.")
    return NodeResult(
        output={
            "text": res.get("text", ""),
            "content": res.get("content", []),
            "structured": res.get("structured"),
            "is_error": bool(res.get("is_error")),
        }
    )


MCP_TOOL = NodeSpec(
    type="mcp_tool",
    label="외부 도구 호출(MCP)",
    category="연동",
    description=(
        "연결해 둔 외부 MCP 서버의 도구 하나를 불러 써요. 어떤 도구가 있는지는 연결 정보 화면의 "
        "'MCP 서버'에서 연결 테스트로 볼 수 있어요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "credential_id": {"type": "string", "title": "MCP 서버(연결 정보)"},
            "tool": {"type": "string", "title": "도구"},
            "arguments": {"type": "object", "title": "넘길 값"},
            "fail_on_tool_error": {
                "type": "boolean",
                "title": "도구가 오류를 알려 주면 이 단계를 실패로 처리",
                "default": False,
            },
        },
        "required": ["credential_id", "tool"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "content": {"type": "array"},
            "structured": {},
            "is_error": {"type": "boolean"},
        },
    },
    ui_schema={
        "credential_id": {"ui:widget": "mcpServer"},
        "tool": {"ui:widget": "mcpTool"},
        "arguments": {"ui:field": "mcpArgs"},
    },
    run=_run_mcp_tool,
    outputs=lambda d: ["text", "content", "structured", "is_error"],
)


# ---------------- API 도구(OpenAPI) ----------------
def _run_api_tool(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    tool_set = str(data.get("tool_set") or "").strip()
    operation = str(data.get("operation") or "").strip()
    if not tool_set:
        raise NodeError("API 도구 묶음을 골라 주세요.")
    if not operation:
        raise NodeError("부를 API 도구를 골라 주세요.")
    params = ctx.render_value(data.get("params") if data.get("params") is not None else {})
    if not isinstance(params, dict):
        raise NodeError("도구에 줄 값은 {이름: 값} 모양이어야 해요. '넘길 값' 칸을 확인하세요.")
    body = ctx.render_value(data.get("body"))
    res = ctx.services.api_tool_call(
        tool_set_id=tool_set, operation=operation, params=params, body=body
    )
    if not res.get("ok") and data.get("fail_on_error_status"):
        raise NodeError(
            f"API가 오류로 답했어요(코드 {res.get('status')}). 넘긴 값과 인증 정보를 확인하세요."
        )
    ctx.log(f"API 도구 '{operation}' → 응답 코드 {res.get('status')}")
    return NodeResult(
        output={
            "status": res.get("status"),
            "ok": bool(res.get("ok")),
            "body": res.get("body"),
            "text": res.get("text", ""),
        }
    )


API_TOOL = NodeSpec(
    type="api_tool",
    label="API 도구 호출",
    category="연동",
    description=(
        "OpenAPI 명세로 가져와 둔 API의 도구(연산) 하나를 불러요. 주소·인증은 가져올 때 정해 둬서 "
        "값만 넣으면 돼요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "tool_set": {"type": "string", "title": "API 도구 묶음"},
            "operation": {"type": "string", "title": "도구"},
            "params": {"type": "object", "title": "넘길 값(주소·검색 조건·헤더)"},
            "body": {"title": "보낼 내용(본문)"},
            "fail_on_error_status": {
                "type": "boolean",
                "title": "응답 코드가 오류(4xx·5xx)이면 이 단계를 실패로 처리",
                "default": False,
            },
        },
        "required": ["tool_set", "operation"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "integer"},
            "ok": {"type": "boolean"},
            "body": {},
            "text": {"type": "string"},
        },
    },
    ui_schema={
        "tool_set": {"ui:widget": "apiToolSet"},
        "operation": {"ui:widget": "apiOperation"},
        "params": {"ui:field": "apiParams"},
        "body": {"ui:field": "json"},
    },
    run=_run_api_tool,
    outputs=lambda d: ["status", "ok", "body", "text"],
)

TOOL_SPECS = [MCP_TOOL, API_TOOL]


def register_tools(reg: NodeRegistry) -> None:
    for spec in TOOL_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
