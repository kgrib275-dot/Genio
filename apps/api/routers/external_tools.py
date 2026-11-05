"""외부 도구 연결(v0.8, ADR 0012): MCP 서버 연결과 OpenAPI로 가져온 API 도구 묶음.

둘 다 '연결 정보'(connector_credentials)에 암호화해 저장하고, 흐름 단계(mcp_tool·api_tool)가
연결 정보 id로 불러 쓴다. 만들기·지우기는 소유자·관리자, 목록·시험은 제작자 이상이 한다.
"""

import json
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.connectors import api_tools, mcp_runtime
from api.core.audit import audit
from api.core.crypto import decrypt_json, encrypt_json
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, MANAGE_SECRETS, Ctx, require_role
from api.market import service as market
from api.models import ConnectorCredential, ConnectorDefinition
from api.services import openapi_tools
from nodes import NodeError

router = APIRouter(tags=["external-tools"])
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]

MAX_MCP_SERVERS = 30
MAX_TOOL_SETS = 20
AUTH_TYPES = ("none", "bearer", "basic", "header")


def _as_app_error(exc: NodeError) -> AppError:
    return AppError(422, exc.message, "입력한 내용을 확인한 뒤 다시 시도하세요.")


def _definition_id(ctx: Ctx, key: str) -> str:
    """연결 정보 종류(key)가 이 워크스페이스에 설치돼 있게 하고 정의 id를 돌려준다."""
    if key not in market.installed_keys(ctx.db, ctx.workspace_id):
        market.install(ctx.db, ctx.workspace_id, key, ctx.user.id)
    items = {i.key: i for i in market.installed_items(ctx.db, ctx.workspace_id, "connector")}
    item = items.get(key)
    definition = (
        ctx.db.scalar(
            select(ConnectorDefinition).where(
                ConnectorDefinition.key == key, ConnectorDefinition.version == item.version
            )
        )
        if item is not None
        else None
    )
    if definition is None:
        raise AppError(
            404,
            "연결 정보 종류를 찾지 못했어요.",
            "마켓에서 해당 항목을 설치한 뒤 다시 시도하세요.",
        )
    return definition.id


def _rows(ctx: Ctx, key: str) -> list[ConnectorCredential]:
    return list(
        ctx.db.scalars(
            select(ConnectorCredential)
            .join(ConnectorDefinition, ConnectorDefinition.id == ConnectorCredential.definition_id)
            .where(
                ConnectorCredential.workspace_id == ctx.workspace_id, ConnectorDefinition.key == key
            )
            .order_by(ConnectorCredential.created_at)
        )
    )


def _row(ctx: Ctx, credential_id: str, key: str) -> ConnectorCredential:
    cred = ctx.db.get(ConnectorCredential, credential_id)
    definition = ctx.db.get(ConnectorDefinition, cred.definition_id) if cred else None
    if (
        cred is None
        or cred.workspace_id != ctx.workspace_id
        or definition is None
        or definition.key != key
    ):
        raise not_found("연결 정보")
    return cred


# ---------------- MCP 서버 ----------------
def _host(url: str) -> str:
    return urlparse(url).hostname or ""


@router.get("/workspaces/{ws}/mcp/servers")
def list_mcp_servers(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    out = []
    for c in _rows(ctx, mcp_runtime.CREDENTIAL_KEY):
        secrets = decrypt_json(c.secret_encrypted)
        out.append(
            {
                "id": c.id,
                "name": c.name,
                # 주소 전체에는 비밀이 섞일 수 있어 호스트만 보여 준다
                "host": _host(str(secrets.get("url") or "")),
                "has_token": bool(secrets.get("token")),
                "created_at": c.created_at,
            }
        )
    return out


class McpServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=1000)
    token: str = Field(default="", max_length=2000)
    header_name: str = Field(default="", max_length=64)


@router.post("/workspaces/{ws}/mcp/servers", status_code=201)
def create_mcp_server(ws: str, body: McpServerIn, ctx: SecretManagers) -> dict[str, Any]:
    url = body.url.strip()
    if not url.lower().startswith(("https://", "http://")) or not _host(url):
        raise AppError(
            422,
            "MCP 서버 주소가 올바르지 않아요.",
            "https://로 시작하는 서버 주소를 넣으세요(예: https://mcp.example.com/mcp).",
        )
    header = body.header_name.strip()
    if header and not all(ch.isalnum() or ch == "-" for ch in header):
        raise AppError(
            422, "헤더 이름이 올바르지 않아요.", "영문·숫자·하이픈만 쓸 수 있어요(예: X-API-Key)."
        )
    if len(_rows(ctx, mcp_runtime.CREDENTIAL_KEY)) >= MAX_MCP_SERVERS:
        raise AppError(
            409,
            f"MCP 서버는 {MAX_MCP_SERVERS}개까지 연결할 수 있어요.",
            "안 쓰는 연결을 지워 주세요.",
        )
    secrets = {"url": url, "token": body.token.strip(), "header_name": header}
    cred = ConnectorCredential(
        workspace_id=ws,
        definition_id=_definition_id(ctx, mcp_runtime.CREDENTIAL_KEY),
        name=body.name.strip(),
        secret_encrypted=encrypt_json({k: v for k, v in secrets.items() if v}),
        created_by=ctx.user.id,
    )
    ctx.db.add(cred)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.create",
        target_type="connector_credential",
        target_id=cred.id,
        meta={"connector": mcp_runtime.CREDENTIAL_KEY, "name": cred.name},
    )
    ctx.db.commit()
    return {"id": cred.id, "name": cred.name, "host": _host(url), "has_token": bool(body.token)}


@router.get("/workspaces/{ws}/mcp/servers/{credential_id}/tools")
def mcp_server_tools(
    ws: str,
    credential_id: str,
    ctx: Builders,
    refresh: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """서버가 가진 도구 목록(연결 테스트). 흐름 단계의 도구 고르기에도 쓴다."""
    _row(ctx, credential_id, mcp_runtime.CREDENTIAL_KEY)
    try:
        tools = mcp_runtime.list_tools(ctx.db, ws, credential_id, use_cache=not refresh)
        ok, message = True, f"연결됐어요. 도구 {len(tools)}개를 찾았어요."
    except NodeError as exc:
        tools, ok, message = [], False, exc.message
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.test",
        target_type="connector_credential",
        target_id=credential_id,
        meta={"ok": ok},
    )
    ctx.db.commit()
    return {"ok": ok, "message": message, "tools": tools}


# ---------------- API 도구(OpenAPI 가져오기) ----------------
class SpecIn(BaseModel):
    url: str | None = Field(default=None, max_length=1000)
    text: str | None = Field(default=None, max_length=2_000_000)


@router.post("/workspaces/{ws}/api-tools/preview")
def preview_api_tools(ws: str, body: SpecIn, ctx: Builders) -> dict[str, Any]:
    """명세를 읽어 도구 목록을 미리 본다(저장하지 않는다)."""
    del ws
    try:
        return openapi_tools.preview(url=body.url, text=body.text)
    except NodeError as exc:
        raise _as_app_error(exc) from None


class ApiToolSetIn(SpecIn):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(default="", max_length=500)
    selected: list[str] = Field(default_factory=list, max_length=200)
    auth_type: str = "none"
    auth_credential_id: str = Field(default="", max_length=64)


@router.post("/workspaces/{ws}/api-tools", status_code=201)
def create_api_tool_set(ws: str, body: ApiToolSetIn, ctx: SecretManagers) -> dict[str, Any]:
    if body.auth_type not in AUTH_TYPES:
        raise AppError(
            422,
            "인증 방식을 알 수 없어요.",
            "없음·Bearer 토큰·아이디/비밀번호·헤더 중에서 고르세요.",
        )
    if body.auth_type != "none":
        auth_cred = ctx.db.get(ConnectorCredential, body.auth_credential_id)
        auth_def = ctx.db.get(ConnectorDefinition, auth_cred.definition_id) if auth_cred else None
        if (
            auth_cred is None
            or auth_cred.workspace_id != ws
            or auth_def is None
            or auth_def.key != "http_credentials"
        ):
            raise AppError(
                422,
                "인증에 쓸 'HTTP 인증 정보'를 찾지 못했어요.",
                "연결 정보에서 HTTP 인증 정보를 먼저 만든 뒤 골라 주세요.",
            )
    if len(_rows(ctx, api_tools.CREDENTIAL_KEY)) >= MAX_TOOL_SETS:
        raise AppError(
            409,
            f"API 도구 묶음은 {MAX_TOOL_SETS}개까지 만들 수 있어요.",
            "안 쓰는 묶음을 지워 주세요.",
        )
    try:
        parsed = openapi_tools.preview(url=body.url, text=body.text)
        operations = openapi_tools.pick(parsed, body.selected)
    except NodeError as exc:
        raise _as_app_error(exc) from None
    base = (body.base_url.strip() or str(parsed["base_url"])).rstrip("/")
    if not base.lower().startswith(("https://", "http://")):
        raise AppError(
            422,
            "기본 주소가 필요해요.",
            "명세에 서버 주소가 없어요. https://로 시작하는 기본 주소를 넣어 주세요.",
        )
    secrets = {
        "operations": json.dumps(operations, ensure_ascii=False),
        "base_url": base,
        "auth_type": body.auth_type,
        "auth_credential_id": body.auth_credential_id if body.auth_type != "none" else "",
    }
    cred = ConnectorCredential(
        workspace_id=ws,
        definition_id=_definition_id(ctx, api_tools.CREDENTIAL_KEY),
        name=body.name.strip(),
        secret_encrypted=encrypt_json({k: v for k, v in secrets.items() if v}),
        created_by=ctx.user.id,
    )
    ctx.db.add(cred)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.create",
        target_type="connector_credential",
        target_id=cred.id,
        meta={"connector": api_tools.CREDENTIAL_KEY, "name": cred.name, "tools": len(operations)},
    )
    ctx.db.commit()
    return {"id": cred.id, "name": cred.name, "tools": len(operations), "base_url": base}


def _set_summary(c: ConnectorCredential) -> dict[str, Any]:
    secrets = decrypt_json(c.secret_encrypted)
    try:
        count = len(json.loads(str(secrets.get("operations") or "[]")))
    except json.JSONDecodeError:
        count = 0
    return {
        "id": c.id,
        "name": c.name,
        "base_url": str(secrets.get("base_url") or ""),
        "tools": count,
        "auth_type": str(secrets.get("auth_type") or "none"),
        "created_at": c.created_at,
    }


@router.get("/workspaces/{ws}/api-tools")
def list_api_tool_sets(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    return [_set_summary(c) for c in _rows(ctx, api_tools.CREDENTIAL_KEY)]


@router.get("/workspaces/{ws}/api-tools/{tool_set_id}")
def get_api_tool_set(ws: str, tool_set_id: str, ctx: Builders) -> dict[str, Any]:
    """도구 묶음 안의 도구 목록(흐름 단계에서 도구와 값 칸을 만들 때 쓴다). 인증 값은 없다."""
    _row(ctx, tool_set_id, api_tools.CREDENTIAL_KEY)
    try:
        tool_set = api_tools.load_set(ctx.db, ws, tool_set_id)
    except NodeError as exc:
        raise _as_app_error(exc) from None
    return {
        "id": tool_set_id,
        "name": tool_set["name"],
        "base_url": tool_set["base_url"],
        "auth_type": tool_set["auth_type"],
        "operations": tool_set["operations"],
    }
