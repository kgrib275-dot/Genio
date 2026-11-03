"""지식베이스: 목록·생성·삭제, 문서 업로드(→ 워커에서 청킹·임베딩), 디버그 검색."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.config import get_settings
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import Chunk, Document, KnowledgeBase
from api.services import knowledge as svc
from api.services.queue import enqueue_document
from nodes import NodeError

router = APIRouter(tags=["knowledge"])
WsViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
KbViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="kb"))]
KbBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="kb"))]
DocBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="document"))]


def _kb(kb: KnowledgeBase, count: int) -> dict[str, Any]:
    return {
        "id": kb.id,
        "name": kb.name,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "created_at": kb.created_at,
        "document_count": count,
    }


@router.get("/workspaces/{ws}/knowledge-bases")
def list_kbs(ws: str, ctx: WsViewers) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(KnowledgeBase, func.count(Document.id))
        .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
        .where(KnowledgeBase.workspace_id == ws)
        .group_by(KnowledgeBase.id)
        .order_by(KnowledgeBase.created_at)
    ).all()
    return [_kb(kb, n) for kb, n in rows]


class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chunk_size: int = Field(default=800, ge=200, le=4000)


@router.post("/workspaces/{ws}/knowledge-bases")
def create_kb(ws: str, body: KbIn, ctx: WsBuilders) -> dict[str, Any]:
    kb = KnowledgeBase(
        workspace_id=ws,
        name=body.name,
        embedding_model=get_settings().genio_embedding_model,
        chunk_size=body.chunk_size,
    )
    ctx.db.add(kb)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="kb.create",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"name": body.name},
    )
    ctx.db.commit()
    return _kb(kb, 0)


@router.delete("/knowledge-bases/{kb_id}", status_code=204)
def delete_kb(kb_id: str, ctx: KbBuilders) -> Response:
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.delete",
        target_type="knowledge_base",
        target_id=kb.id,
        meta={"name": kb.name},
    )
    ctx.db.delete(kb)
    ctx.db.commit()
    return Response(status_code=204)


def _doc(d: Document, chunks: int) -> dict[str, Any]:
    return {
        "id": d.id,
        "kb_id": d.kb_id,
        "filename": d.filename,
        "mime": d.mime,
        "size": d.size,
        "status": d.status,
        "error": d.error,
        "created_at": d.created_at,
        "chunk_count": chunks,
    }


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(
    kb_id: str, ctx: KbBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    filename = file.filename or "document"
    mime = file.content_type or "application/octet-stream"
    if svc.kind_of(filename, mime) is None:
        raise AppError(
            415, "PDF, TXT, MD 파일만 올릴 수 있어요.", "파일 형식을 바꿔서 다시 올려 주세요."
        )
    content = await file.read(svc.MAX_UPLOAD_BYTES + 1)
    if len(content) > svc.MAX_UPLOAD_BYTES:
        raise AppError(413, "파일이 너무 커요(최대 20MB).", "파일을 나눠서 올려 주세요.")
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        mime=mime,
        size=len(content),
        status="uploaded",
        content=content,
    )
    ctx.db.add(doc)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="kb.document_upload",
        target_type="document",
        target_id=doc.id,
        meta={"filename": filename},
    )
    ctx.db.commit()
    enqueue_document(doc.id)
    ctx.db.refresh(doc)
    count = ctx.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)) or 0
    return _doc(doc, count)


@router.get("/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: str, ctx: KbViewers) -> list[dict[str, Any]]:
    counts = dict(
        ctx.db.execute(
            select(Chunk.document_id, func.count(Chunk.id))
            .where(Chunk.kb_id == kb_id)
            .group_by(Chunk.document_id)
        ).all()
    )
    rows = ctx.db.scalars(
        select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
    )
    return [_doc(d, int(counts.get(d.id, 0))) for d in rows]


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, ctx: DocBuilders) -> Response:
    doc = ctx.db.get(Document, document_id)
    if doc is None:
        raise not_found("문서")
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="kb.document_delete",
        target_type="document",
        target_id=doc.id,
        meta={"filename": doc.filename},
    )
    ctx.db.delete(doc)
    ctx.db.commit()
    return Response(status_code=204)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=20)


@router.post("/knowledge-bases/{kb_id}/search")
def search(kb_id: str, body: SearchIn, ctx: KbBuilders) -> list[dict[str, Any]]:
    try:
        return svc.search(ctx.db, ctx.workspace_id, kb_id, body.query, body.top_k)
    except NodeError as exc:
        raise AppError(400, exc.message, "AI 연결 설정을 확인한 뒤 다시 검색하세요.") from exc
