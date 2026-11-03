"""v0.6 MCP 서버로 게시(ADR 0010): 앱 하나를 MCP 도구 하나로 내놓는다.

- 전송: MCP Streamable HTTP(JSON-RPC 2.0, POST 한 번에 JSON 응답). 세션 없이 동작한다(Mcp-Session-Id 없음).
  서버가 먼저 보내는 SSE 스트림은 없으므로 GET·DELETE는 405.
- 지원 메서드: initialize, notifications/initialized(및 다른 알림), ping, tools/list, tools/call.
- 프로토콜 버전: 클라이언트가 보낸 버전이 지원 목록에 있으면 그대로, 아니면 최신 지원 버전으로 답한다.
- 인증: 앱 API 키(Authorization: Bearer gk-...)에 'mcp' 권한이 있어야 하고, 앱 기능에서 MCP 게시를 켜야 한다.
  키·IP별 분당 60회(서비스 API와 같은 제한) + 키별 분당 MCP_RATE_PER_MINUTE회.
"""

import re
import time
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.errors import AppError
from api.db import SessionLocal
from api.deps import DbDep
from api.models import App, Run
from api.routers.service import AppKeyCtx, app_key, need_scope
from api.services.app_config import merged_features
from api.services.chat import ChatRequest, input_fields, run_chat, start_chat
from api.services.queue import enqueue_run

router = APIRouter(prefix="/service", tags=["mcp"])

# 최신이 앞(검증한 공개 사양 버전). 모르는 버전을 보내면 맨 앞 버전으로 답한다.
SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MCP_RATE_PER_MINUTE = 120
CALL_WAIT_SECONDS = 60
SERVER_VERSION = "0.6.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_JSON_TYPES = {"number": "number", "boolean": "boolean", "file": "string", "paragraph": "string"}


def tool_name(app: App) -> str:
    """도구 이름: 앱 기능에서 정한 이름, 없으면 앱 이름의 영문·숫자, 그것도 없으면 app_<id 앞 8자리>."""
    custom = str(merged_features(app.features)["mcp"].get("tool_name") or "")
    if custom:
        return custom
    slug = re.sub(r"[^A-Za-z0-9]+", "_", app.name or "").strip("_").lower()[:48]
    return slug or f"app_{app.id.replace('-', '')[:8]}"


def tool_def(k: AppKeyCtx) -> dict[str, Any]:
    app = k.app
    feat = merged_features(app.features)["mcp"]
    fields = input_fields(k.version.graph)
    props: dict[str, Any] = {}
    required: list[str] = []
    if app.type == "chat":
        props["query"] = {"type": "string", "description": "챗봇에게 보낼 말"}
        required.append("query")
    for f in fields:
        key = str(f["key"])
        if key in props:
            continue
        props[key] = {
            "type": _JSON_TYPES.get(str(f.get("type") or "text"), "string"),
            "description": str(f.get("label") or key),
        }
        if f.get("required") and app.type != "chat":
            required.append(key)
    description = (
        str(feat.get("description") or "")
        or (app.description or "")
        or f"Genio 앱 '{app.name}'을(를) 실행해 결과 글을 돌려줘요."
    )
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return {
        "name": tool_name(app),
        "title": app.name,
        "description": description[:1000],
        "inputSchema": schema,
    }


def _rpc_result(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _tool_error(message: str, hint: str) -> dict[str, Any]:
    """도구 실행 오류(MCP isError): 무엇이 문제인지 + 어떻게 하면 되는지 두 줄."""
    return {"content": [{"type": "text", "text": f"{message}\n{hint}"}], "isError": True}


def _run_workflow(db: Session, k: AppKeyCtx, args: dict[str, Any]) -> dict[str, Any]:
    run = Run(app_id=k.app.id, version_id=k.version.id, trigger="mcp", input=args)
    db.add(run)
    db.commit()
    run_id = run.id
    enqueue_run(run_id)
    deadline = time.time() + CALL_WAIT_SECONDS
    while True:
        with SessionLocal() as s:
            r = s.get(Run, run_id)
            status = r.status if r else "failed"
            if r is not None and status in ("succeeded", "failed", "waiting_approval"):
                out = dict(r.output or {})
                error = r.error
                break
        if time.time() >= deadline:
            return _tool_error(
                f"{CALL_WAIT_SECONDS}초 안에 실행이 끝나지 않았어요(실행 번호 {run_id}).",
                "흐름을 짧게 만들거나, 서비스 API의 실행 결과 읽기로 나중에 확인하세요.",
            )
        time.sleep(0.3)
    if status == "waiting_approval":
        return _tool_error(
            "흐름이 사람의 승인·답을 기다리고 있어요.",
            f"작업함에서 처리하면 이어서 실행돼요(실행 번호 {run_id}).",
        )
    if status != "succeeded":
        return _tool_error(
            f"실행이 실패했어요: {error or '원인을 알 수 없어요.'}",
            "입력값을 확인하거나 앱의 실행 기록에서 실패한 단계를 살펴보세요.",
        )
    text = str(out.get("text") or "")
    return {
        "content": [{"type": "text", "text": text or "(결과 글이 비어 있어요)"}],
        "structuredContent": {"text": text, "outputs": out.get("outputs") or {}, "run_id": run_id},
        "isError": False,
    }


def _run_chat(db: Session, k: AppKeyCtx, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.pop("query", "") or "").strip()
    if not query:
        return _tool_error(
            "'query'(보낼 말)가 비어 있어요.", "챗봇에게 보낼 말을 query에 넣으세요."
        )
    req = ChatRequest(
        app=k.app,
        version=k.version,
        deployment=None,
        user_id=None,
        message=query[:4000],
        session_id=None,
        inputs=args,
    )
    conv, _ = start_chat(db, req)
    answer, status, run_id = "", "failed", None
    for name, data in run_chat(
        conv.id, k.app.id, k.version.id, None, query[:4000], args, [], trigger="mcp"
    ):
        if name in ("answer", "moderated", "annotated") and isinstance(data, dict):
            answer = str(data.get("text", ""))
        elif name == "error" and isinstance(data, dict):
            return _tool_error(str(data.get("message")), str(data.get("hint")))
        elif name == "done" and isinstance(data, dict):
            status, run_id = str(data.get("status")), data.get("run_id")
    if status == "failed" and not answer:
        return _tool_error(
            "챗봇이 답하지 못했어요.", "앱의 대화 기록에서 원인을 확인하고 다시 시도하세요."
        )
    return {
        "content": [{"type": "text", "text": answer}],
        "structuredContent": {"text": answer, "run_id": run_id, "status": status},
        "isError": False,
    }


def _call(db: Session, k: AppKeyCtx, params: dict[str, Any], rid: Any) -> dict[str, Any]:
    name = str(params.get("name") or "")
    if name != tool_name(k.app):
        return _rpc_error(rid, INVALID_PARAMS, f"Unknown tool: {name}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _rpc_error(rid, INVALID_PARAMS, "arguments must be an object")
    args = {str(a): v for a, v in args.items() if not str(a).startswith("__")}
    if len(str(args)) > 20_000:
        return _rpc_result(
            rid, _tool_error("입력이 너무 커요(최대 20KB).", "긴 글은 줄이거나 나눠서 보내세요.")
        )
    if k.app.type != "chat":
        missing = [
            str(f["key"])
            for f in input_fields(k.version.graph)
            if f.get("required") and args.get(str(f["key"])) in (None, "")
        ]
        if missing:
            return _rpc_result(
                rid,
                _tool_error(
                    f"'{', '.join(missing)}' 값이 빠졌어요.",
                    "도구 설명(inputSchema)의 필수 항목을 모두 채워서 다시 부르세요.",
                ),
            )
        return _rpc_result(rid, _run_workflow(db, k, args))
    return _rpc_result(rid, _run_chat(db, k, args))


def _handle(db: Session, k: AppKeyCtx, msg: Any) -> dict[str, Any] | None:
    """메시지 하나 처리. 알림(id 없음)이면 None."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(
            msg.get("id") if isinstance(msg, dict) else None,
            INVALID_REQUEST,
            "Invalid Request",
        )
    method = str(msg["method"])
    is_notification = "id" not in msg
    rid = msg.get("id")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return None if is_notification else _rpc_error(rid, INVALID_PARAMS, "params must be object")
    if is_notification:
        return None  # notifications/initialized 등: 받기만 한다
    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _rpc_result(
            rid,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "genio", "title": "Genio", "version": SERVER_VERSION},
                "instructions": f"Genio 앱 '{k.app.name}'을(를) 도구 하나로 부를 수 있어요.",
            },
        )
    if method == "ping":
        return _rpc_result(rid, {})
    if method == "tools/list":
        return _rpc_result(rid, {"tools": [tool_def(k)]})
    if method == "tools/call":
        return _call(db, k, params, rid)
    if method in ("resources/list", "prompts/list"):
        key = "resources" if method == "resources/list" else "prompts"
        return _rpc_result(rid, {key: []})
    return _rpc_error(rid, METHOD_NOT_FOUND, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_post(request: Request, db: DbDep) -> Response:
    k = app_key(request, db)
    need_scope(k, "mcp")
    if not merged_features(k.app.features)["mcp"]["enabled"]:
        raise AppError(
            403,
            "이 앱은 MCP로 게시돼 있지 않아요.",
            "앱의 API 화면에서 'MCP로 게시'를 켜세요.",
        )
    if not ratelimit.allow(f"mcp:{k.key.id}", MCP_RATE_PER_MINUTE):
        raise AppError(429, "MCP 요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    header_version = request.headers.get("mcp-protocol-version")
    if header_version and header_version not in SUPPORTED_VERSIONS:
        return JSONResponse(
            _rpc_error(None, INVALID_REQUEST, f"Unsupported protocol version: {header_version}"),
            status_code=400,
        )
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(_rpc_error(None, PARSE_ERROR, "Parse error"), status_code=400)
    from starlette.concurrency import run_in_threadpool

    if isinstance(payload, list):  # 2025-03-26 일괄 요청
        if not payload or len(payload) > 20:
            return JSONResponse(_rpc_error(None, INVALID_REQUEST, "Invalid batch"), status_code=400)
        answers = []
        for m in payload:
            a = await run_in_threadpool(_handle, db, k, m)
            if a is not None:
                answers.append(a)
        if not answers:
            return Response(status_code=202)
        return JSONResponse(answers)
    answer = await run_in_threadpool(_handle, db, k, payload)
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(answer)


@router.get("/mcp")
def mcp_get() -> Response:
    """서버가 먼저 보내는 SSE 스트림은 제공하지 않는다(사양상 405로 알린다)."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
def mcp_delete() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
