"""전체 검색창(Ctrl+K) API(v0.8). 로그인한 워크스페이스 멤버면 누구나 쓰되, 결과는 역할에 맞는 것만."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from api.deps import ANY_MEMBER, Ctx, require_role
from api.services.search import search_workspace

router = APIRouter(tags=["search"])
WsMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]


@router.get("/workspaces/{ws}/search")
def search(
    ws: str,
    ctx: WsMembers,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> dict[str, Any]:
    """앱·프로젝트·지식베이스·데이터 표·연결 정보·마켓·화면을 한 번에 찾는다(그룹별 최대 limit개)."""
    return {
        "query": q.strip(),
        "groups": search_workspace(ctx.db, ws, ctx.user.id, ctx.role, q, limit),
    }
