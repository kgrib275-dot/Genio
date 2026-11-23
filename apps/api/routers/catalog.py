"""외부 카탈로그(ADR 0020): 공식 MCP 레지스트리에서 서비스를 찾아 연결 정보로 설치한다.
회사가 '안전·규칙'에서 켜야 쓸 수 있다(기본 꺼짐)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, MANAGE_SECRETS, Ctx, require_role
from api.models import Workspace
from api.routers.dify_import import create_from_converted
from api.routers.external_tools import McpServerIn, create_mcp_server
from api.routers.projects import check_project_target
from api.services import catalog, n8n_import, trends
from nodes import NodeError

router = APIRouter(tags=["catalog"])
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]


def catalog_enabled(ctx: Ctx) -> bool:
    w = ctx.db.get(Workspace, ctx.workspace_id)
    return bool(((w.settings if w else None) or {}).get("security", {}).get("external_catalog"))


def _require_enabled(ctx: Ctx) -> None:
    if not catalog_enabled(ctx):
        raise AppError(
            403,
            "이 회사는 외부 서비스 찾기를 아직 켜지 않았어요.",
            "소유자나 관리자가 '안전·규칙 > 외부 서비스 찾기'를 켠 뒤 다시 시도하세요.",
        )


@router.get("/workspaces/{ws}/catalog/mcp")
def search_mcp(
    ws: str,
    ctx: Builders,
    q: Annotated[str, Query(max_length=100)] = "",
    cursor: Annotated[str, Query(max_length=200)] = "",
) -> dict[str, Any]:
    _require_enabled(ctx)
    if not ratelimit.allow(f"catalog:{ctx.user.id}", 20, window=60):
        raise AppError(429, "너무 자주 찾고 있어요.", "잠시(1분 정도) 쉬었다가 다시 검색해 주세요.")
    try:
        result = catalog.search_mcp(q, cursor)
    except NodeError as exc:
        raise AppError(502, exc.message, "잠시 후 다시 시도하세요.") from None
    if ratelimit.allow(f"catalog_log:{ctx.user.id}:{ws}", 1, window=600):
        audit(
            ctx.db,
            workspace_id=ws,
            user_id=ctx.user.id,
            action="catalog.search",
            target_type="workspace",
            target_id=ws,
            meta={"source": "mcp-registry", "q": q[:60]},
        )
        ctx.db.commit()
    return {**result, "enabled": True}


class InstallIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    remote: int = Field(default=0, ge=0, le=9)
    display_name: str = Field(default="", max_length=100)
    token: str = Field(default="", max_length=2000)
    header_name: str = Field(default="", max_length=64)


@router.post("/workspaces/{ws}/catalog/mcp/install", status_code=201)
def install_mcp(ws: str, body: InstallIn, ctx: SecretManagers) -> dict[str, Any]:
    _require_enabled(ctx)
    try:
        item = catalog.find_mcp(body.name)
    except NodeError as exc:
        raise AppError(502, exc.message, "잠시 후 다시 시도하세요.") from None
    if item is None or not item["installable"] or body.remote >= len(item["remotes"]):
        raise AppError(
            404,
            "이 서비스는 바로 연결할 수 없어요.",
            "목록에서 '연결하기'가 있는 서비스를 고르거나, 서버 주소를 직접 넣어 연결하세요.",
        )
    remote = item["remotes"][body.remote]
    header = body.header_name.strip()
    if body.token and not header:
        # 레지스트리가 알려 준 비밀 헤더 이름을 쓴다(없으면 기본 Authorization: Bearer)
        named = [h["name"] for h in remote["headers"] if h["secret"]]
        header = "" if not named or named[0] == "Authorization" else named[0]
    made = create_mcp_server(
        ws,
        McpServerIn(
            name=body.display_name.strip() or item["title"],
            url=remote["url"],
            token=body.token,
            header_name=header,
        ),
        ctx,
    )
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="catalog.install",
        target_type="connector_credential",
        target_id=made["id"],
        meta={"source": "mcp-registry", "name": item["name"], "version": item["version"]},
    )
    ctx.db.commit()
    return {**made, "source": item["name"], "repository": item["repository"]}


# ---------------- n8n 공개 템플릿 ----------------
@router.get("/workspaces/{ws}/catalog/n8n")
def search_n8n(
    ws: str,
    ctx: Builders,
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=50)] = 1,
) -> dict[str, Any]:
    _require_enabled(ctx)
    if not ratelimit.allow(f"catalog:{ctx.user.id}", 20, window=60):
        raise AppError(429, "너무 자주 찾고 있어요.", "잠시(1분 정도) 쉬었다가 다시 검색해 주세요.")
    try:
        result = catalog.search_n8n(q, page)
    except NodeError as exc:
        raise AppError(502, exc.message, "잠시 후 다시 시도하세요.") from None
    if ratelimit.allow(f"catalog_log:{ctx.user.id}:{ws}", 1, window=600):
        audit(
            ctx.db,
            workspace_id=ws,
            user_id=ctx.user.id,
            action="catalog.search",
            target_type="workspace",
            target_id=ws,
            meta={"source": "n8n-templates", "q": q[:60]},
        )
        ctx.db.commit()
    return result


class N8nImportIn(BaseModel):
    id: int = Field(ge=1, le=10_000_000)
    project_id: str | None = Field(default=None, max_length=64)


@router.post("/workspaces/{ws}/catalog/n8n/import", status_code=201)
def import_n8n(ws: str, body: N8nImportIn, ctx: Builders) -> dict[str, Any]:
    """n8n 템플릿을 제니오 초안 앱으로 가져온다. 옮기지 못한 단계는 꺼 둔 자리 표시로 남고 보고서에 적힌다."""
    _require_enabled(ctx)
    check_project_target(ctx, ws, body.project_id)
    try:
        tpl = catalog.get_n8n(body.id)
    except NodeError as exc:
        raise AppError(
            502, exc.message, "다른 템플릿을 고르거나 잠시 후 다시 시도하세요."
        ) from None
    if tpl["paid"]:
        raise AppError(403, "유료 템플릿은 가져올 수 없어요.", "무료 템플릿을 골라 주세요.")
    conv = n8n_import.convert(
        tpl["workflow"],
        name=tpl["name"],
        description=tpl["description"],
        source=f"n8n 템플릿 #{tpl['id']}({tpl['author'] or '작성자 미상'}, {tpl['url']})",
    )
    return create_from_converted(
        ctx,
        ws,
        conv,
        body.project_id,
        action="catalog.import_n8n",
        meta={"source": "n8n-templates", "template_id": tpl["id"], "author": tpl["author"]},
    )


@router.get("/workspaces/{ws}/catalog/trends")
def catalog_trends(ws: str, ctx: Builders) -> dict[str, Any]:
    """이번 주 새로 나온 MCP 서비스와 n8n 최신·인기 템플릿(하루 한 번 모아 둔 목록)."""
    _require_enabled(ctx)
    if not ratelimit.allow(f"catalog:{ctx.user.id}", 20, window=60):
        raise AppError(429, "너무 자주 찾고 있어요.", "잠시(1분 정도) 쉬었다가 다시 열어 주세요.")
    data = trends.get()
    if ratelimit.allow(f"catalog_log:{ctx.user.id}:{ws}", 1, window=600):
        audit(
            ctx.db,
            workspace_id=ws,
            user_id=ctx.user.id,
            action="catalog.search",
            target_type="workspace",
            target_id=ws,
            meta={"source": "trends"},
        )
        ctx.db.commit()
    return data
