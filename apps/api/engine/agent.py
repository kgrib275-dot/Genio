"""agent 단계: AI가 도구(웹 읽기·지식 검색·서비스 연결·다른 앱)를 스스로 골라 쓰는 루프."""

import json
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from api.engine import safe_http
from api.llm.base import LlmError, Message, ToolDef
from api.llm.chain import pop_notes
from api.llm.registry import resolve_llm
from api.models import App, ConnectorCredential, Run, WorkflowVersion
from nodes import NodeError

if TYPE_CHECKING:
    from api.engine.executor import RunServices

MAX_TOOL_OUTPUT = 4000
MAX_DEPTH = 2
MAX_MCP_TOOLS = 20


def _safe_name(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)[:60] or "tool"


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_tools(
    services: "RunServices", tools: list[dict[str, Any]]
) -> tuple[list[ToolDef], dict[str, dict[str, Any]]]:
    defs: list[ToolDef] = []
    table: dict[str, dict[str, Any]] = {}
    for i, t in enumerate(tools):
        kind = str(t.get("type"))
        desc = str(t.get("description") or "")
        if kind == "web":
            name = "read_web_page"
            defs.append(
                ToolDef(
                    name,
                    desc or "공개 웹 페이지의 글을 읽어 온다.",
                    {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                )
            )
        elif kind == "knowledge":
            name = _safe_name(f"search_kb_{i}")
            defs.append(
                ToolDef(
                    name,
                    desc or "지식베이스에서 관련 내용을 찾는다.",
                    {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                )
            )
        elif kind == "connector":
            manifest = services.connector_manifest(str(t.get("connector") or ""))
            action = next(
                (a for a in (manifest or {}).get("actions", []) if a.get("key") == t.get("action")),
                None,
            )
            if action is None:
                raise NodeError(
                    f"에이전트 도구 '{t.get('connector')}.{t.get('action')}'을(를) 찾지 못했어요. 마켓 설치를 확인하세요."
                )
            name = _safe_name(f"{t.get('connector')}__{t.get('action')}")
            defs.append(
                ToolDef(
                    name,
                    desc or str(action.get("label") or name),
                    action.get("input_schema") or {"type": "object"},
                )
            )
        elif kind == "mcp":
            # MCP 서버 하나의 도구 여러 개를 한 번에 연다(이름을 적으면 그것만, 비우면 앞의 20개)
            cred = str(t.get("credential_id") or "")
            if not cred:
                raise NodeError("에이전트의 MCP 도구에 쓸 연결 정보를 골라 주세요.")
            wanted = [str(n) for n in (t.get("tools") or []) if str(n).strip()]
            found = {x["name"]: x for x in services.mcp_tools(credential_id=cred)}
            missing = [n for n in wanted if n not in found]
            if missing:
                raise NodeError(
                    f"MCP 서버에서 도구 '{', '.join(missing)}'을(를) 찾지 못했어요. 연결 정보의 연결 테스트로 도구 이름을 확인하세요."
                )
            chosen = [found[n] for n in wanted] if wanted else list(found.values())
            for j, tool in enumerate(chosen[:MAX_MCP_TOOLS]):
                name = _safe_name(f"mcp{i}_{j}_{tool['name']}")
                defs.append(
                    ToolDef(
                        name,
                        str(tool.get("description") or tool["name"]),
                        tool.get("input_schema") or {"type": "object"},
                    )
                )
                table[name] = {"type": "mcp", "credential_id": cred, "tool": tool["name"]}
            continue
        elif kind == "app":
            app = services.db.get(App, str(t.get("app_id") or ""))
            if app is None or app.workspace_id != services.workspace_id:
                raise NodeError("에이전트가 부를 앱을 찾지 못했어요.")
            name = _safe_name(f"app_{app.slug}")
            defs.append(
                ToolDef(
                    name,
                    desc or f"'{app.name}' 앱을 실행한다. {app.description}",
                    {
                        "type": "object",
                        "properties": {"inputs": {"type": "object", "description": "앱 입력 항목"}},
                        "required": ["inputs"],
                    },
                )
            )
        else:
            continue
        table[name] = t
    return defs, table


def call_tool(services: "RunServices", spec: dict[str, Any], args: dict[str, Any]) -> str:
    kind = spec.get("type")
    if kind == "web":
        res = safe_http.request("GET", str(args.get("url", "")))
        body = res.get("body")
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        return _strip_html(text)[:MAX_TOOL_OUTPUT]
    if kind == "knowledge":
        hits = services.kb_search(
            kb_id=str(spec.get("kb_id") or ""), query=str(args.get("query", "")), top_k=4
        )
        return (
            "\n\n".join(f"[{h.get('filename')}] {h.get('content')}" for h in hits)[:MAX_TOOL_OUTPUT]
            or "찾은 내용이 없어요."
        )
    if kind == "connector":
        cred = str(spec.get("credential_id") or "")
        if not cred or services.db.get(ConnectorCredential, cred) is None:
            raise NodeError("에이전트 도구의 연결 정보가 없어요. 단계 설정에서 골라 주세요.")
        out = services.run_connector(
            connector=str(spec["connector"]),
            credential_id=cred,
            action=str(spec["action"]),
            params=args,
        )
        return json.dumps(out, ensure_ascii=False)[:MAX_TOOL_OUTPUT]
    if kind == "mcp":
        out = services.mcp_call(
            credential_id=str(spec.get("credential_id") or ""),
            tool=str(spec.get("tool") or ""),
            arguments=args,
        )
        text = str(out.get("text") or "") or json.dumps(out.get("content"), ensure_ascii=False)
        prefix = "(도구가 오류를 알려 줬어요) " if out.get("is_error") else ""
        return (prefix + text)[:MAX_TOOL_OUTPUT]
    if kind == "app":
        return run_child_app(services, str(spec.get("app_id")), dict(args.get("inputs") or {}))
    raise NodeError("알 수 없는 도구예요.")


def run_child_app(services: "RunServices", app_id: str, inputs: dict[str, Any]) -> str:
    """다른 앱(최신 버전)을 도구처럼 실행하고 결과 글을 돌려준다."""
    from api.engine.executor import _execute

    if services.depth >= MAX_DEPTH:
        raise NodeError("앱이 앱을 너무 깊게 부르고 있어요(최대 2단계).")
    version = services.db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.app_id == app_id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    if version is None:
        raise NodeError("도구로 쓰려는 앱에 저장된 버전이 없어요.")
    run = Run(
        app_id=app_id,
        version_id=version.id,
        trigger="tool",
        input={**inputs, "__depth": services.depth + 1},
    )
    services.db.add(run)
    services.db.commit()
    _execute(services.db, run.id)
    services.db.refresh(run)
    if run.status != "succeeded":
        return f"앱 실행이 끝나지 않았어요({run.status}): {run.error or ''}"
    return str((run.output or {}).get("text", ""))[:MAX_TOOL_OUTPUT]


def run_agent(
    services: "RunServices",
    *,
    provider: str,
    model: str | None,
    instruction: str,
    query: str,
    tools: list[dict[str, Any]],
    max_iterations: int,
) -> dict[str, Any]:
    try:
        llm = resolve_llm(
            services.db, services.workspace_id, provider, model, fallback=services.app_fallback
        )
    except LlmError as exc:
        raise NodeError(f"{exc.message} {exc.hint}") from None
    defs, table = build_tools(services, tools)
    system = (
        "당신은 업무를 대신 처리하는 에이전트입니다. 필요하면 도구를 써서 사실을 확인한 뒤 한국어로 간결하게 답하세요. "
        "도구 결과에 없는 내용은 지어내지 마세요.\n" + instruction
    )
    messages: list[Message] = [{"role": "user", "content": query}]
    calls: list[dict[str, Any]] = []
    text = ""
    for _ in range(max_iterations + 1):
        try:
            turn = llm.adapter.chat(model=llm.model, system=system, messages=messages, tools=defs)
        except LlmError as exc:
            raise NodeError(f"{exc.message} {exc.hint}", retryable=exc.retryable) from None
        finally:
            services.notes.extend(pop_notes(llm.adapter))
        services.usage.append((turn.model or llm.model, turn.input_tokens, turn.output_tokens))
        text = turn.text
        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": turn.tool_calls,
                "native": turn.native,
            }
        )
        if not turn.tool_calls or len(calls) >= max_iterations:
            break
        for call in turn.tool_calls:
            spec = table.get(call.name)
            try:
                if spec is None:
                    raise NodeError(f"없는 도구: {call.name}")
                result, ok = call_tool(services, spec, call.input), True
            except NodeError as exc:
                result, ok = exc.message, False
            calls.append(
                {"name": call.name, "input": call.input, "ok": ok, "summary": result[:200]}
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": result,
                    "is_error": not ok,
                }
            )
    return {"text": text, "tool_calls": calls}
