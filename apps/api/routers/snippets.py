"""스니펫(v0.8): 자주 쓰는 단계 묶음. 읽기는 모든 멤버, 만들기·고치기·지우기는 제작자 이상."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, Ctx, require_role
from api.models import Snippet
from api.services.snippets import MAX_SNIPPETS, build_snippet_graph, snippet_dict

router = APIRouter(tags=["snippets"])
WsMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


def _get(ctx: Ctx, ws: str, snippet_id: str) -> Snippet:
    s = ctx.db.get(Snippet, snippet_id)
    if s is None or s.workspace_id != ws:
        raise not_found("스니펫")
    return s


@router.get("/workspaces/{ws}/snippets")
def list_snippets(ws: str, ctx: WsMembers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(Snippet).where(Snippet.workspace_id == ws).order_by(Snippet.created_at.desc())
    )
    return [snippet_dict(s) for s in rows]


@router.get("/workspaces/{ws}/snippets/{snippet_id}")
def get_snippet(ws: str, snippet_id: str, ctx: WsMembers) -> dict[str, Any]:
    return snippet_dict(_get(ctx, ws, snippet_id), with_graph=True)


class SnippetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


@router.post("/workspaces/{ws}/snippets", status_code=201)
def create_snippet(ws: str, body: SnippetIn, ctx: WsBuilders) -> dict[str, Any]:
    count = ctx.db.scalar(
        select(func.count()).select_from(Snippet).where(Snippet.workspace_id == ws)
    )
    if (count or 0) >= MAX_SNIPPETS:
        raise AppError(
            409,
            f"스니펫은 워크스페이스에 {MAX_SNIPPETS}개까지 저장할 수 있어요.",
            "안 쓰는 스니펫을 지운 뒤 다시 저장하세요.",
        )
    graph = build_snippet_graph(body.nodes, body.edges)
    s = Snippet(
        workspace_id=ws,
        name=body.name.strip(),
        description=body.description.strip(),
        graph=graph,
        created_by=ctx.user.id,
    )
    ctx.db.add(s)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="snippet.create",
        target_type="snippet",
        target_id=s.id,
        meta={"name": s.name, "nodes": len(graph["nodes"])},
    )
    ctx.db.commit()
    return snippet_dict(s, with_graph=True)


class SnippetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


@router.patch("/workspaces/{ws}/snippets/{snippet_id}")
def update_snippet(ws: str, snippet_id: str, body: SnippetPatch, ctx: WsBuilders) -> dict[str, Any]:
    s = _get(ctx, ws, snippet_id)
    if body.name is not None:
        s.name = body.name.strip()
    if body.description is not None:
        s.description = body.description.strip()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="snippet.update",
        target_type="snippet",
        target_id=s.id,
    )
    ctx.db.commit()
    return snippet_dict(s)


@router.delete("/workspaces/{ws}/snippets/{snippet_id}", status_code=204)
def delete_snippet(ws: str, snippet_id: str, ctx: WsBuilders) -> Response:
    s = _get(ctx, ws, snippet_id)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="snippet.delete",
        target_type="snippet",
        target_id=s.id,
        meta={"name": s.name},
    )
    ctx.db.delete(s)
    ctx.db.commit()
    return Response(status_code=204)
