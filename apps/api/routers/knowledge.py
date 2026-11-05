"""지식베이스: 목록·생성·삭제, 문서 업로드(→ 워커에서 청킹·임베딩), 디버그 검색."""

import json
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.config import get_settings
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, CurrentUser, require_role
from api.engine import safe_http
from api.llm.catalog import catalog
from api.models import Chunk, Document, KnowledgeBase
from api.routers.projects import check_project_target
from api.services import kb_limits
from api.services import kb_pipeline as pipe
from api.services import knowledge as svc
from api.services.projects import hidden_project_ids
from api.services.queue import enqueue_document
from nodes import NodeError

router = APIRouter(tags=["knowledge"])
WsViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
KbViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="kb"))]
KbBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="kb"))]
DocBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="document"))]


def _kb(kb: KnowledgeBase, count: int) -> dict[str, Any]:
    settings = svc.kb_settings(kb)
    return {
        "kind": settings["kind"],
        "settings": settings,
        "project_id": kb.project_id,
        "id": kb.id,
        "name": kb.name,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "created_at": kb.created_at,
        "document_count": count,
    }


@router.get("/workspaces/{ws}/knowledge-bases")
def list_kbs(ws: str, ctx: WsViewers, project: str | None = None) -> list[dict[str, Any]]:
    q = (
        select(KnowledgeBase, func.count(Document.id))
        .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
        .where(KnowledgeBase.workspace_id == ws)
        .group_by(KnowledgeBase.id)
        .order_by(KnowledgeBase.created_at)
    )
    if project == "none":
        q = q.where(KnowledgeBase.project_id.is_(None))
    elif project:
        q = q.where(KnowledgeBase.project_id == project)
    hidden = hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    rows = ctx.db.execute(q).all()
    return [_kb(kb, n) for kb, n in rows if kb.project_id not in hidden]


class ExternalIn(BaseModel):
    """외부 지식베이스 연결(주소·지식 id·API 키가 든 연결 정보 id)."""

    endpoint: str = Field(min_length=8, max_length=500)
    knowledge_id: str = Field(min_length=1, max_length=200)
    credential_id: str | None = Field(default=None, max_length=64)


class KbIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    chunk_size: int = Field(default=800, ge=200, le=4000)
    project_id: str | None = None
    # 지식베이스마다 고정(만든 뒤에는 바꿀 수 없음 — 바꾸면 이미 만든 조각과 비교할 수 없다)
    embedding_model: str | None = Field(default=None, max_length=100)
    # v0.8: 외부 지식베이스(고객의 검색 서비스 연결). 문서를 올리지 않는다
    kind: Literal["internal", "external"] = "internal"
    external: ExternalIn | None = None


def _embedding_model(name: str | None) -> str:
    model = (name or "").strip() or get_settings().genio_embedding_model
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", model):
        raise AppError(
            422,
            "임베딩 모델 이름이 올바르지 않아요.",
            "목록에서 고르거나 영문 모델 이름을 적으세요.",
        )
    return model


@router.get("/llm/embedding-models")
def embedding_models(user: CurrentUser) -> list[dict[str, Any]]:
    """지식베이스를 만들 때 고를 수 있는 임베딩 모델(카탈로그)."""
    del user
    return [m for m in catalog() if m["embedding"]]


@router.post("/workspaces/{ws}/knowledge-bases")
def create_kb(ws: str, body: KbIn, ctx: WsBuilders) -> dict[str, Any]:
    check_project_target(ctx, ws, body.project_id)
    settings: dict[str, Any] = {}
    if body.kind == "external":
        if body.external is None:
            raise AppError(
                422,
                "외부 지식베이스는 서비스 주소와 지식 id가 필요해요.",
                "주소·지식 id·API 키(연결 정보)를 채워 주세요.",
            )
        from api.routers.knowledge_v08 import clean_external

        settings = {"kind": "external", "external": clean_external(ctx.db, ws, body.external)}
    kb = KnowledgeBase(
        project_id=body.project_id or None,
        workspace_id=ws,
        name=body.name,
        embedding_model=_embedding_model(body.embedding_model),
        chunk_size=body.chunk_size,
        settings=settings,
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


def visible_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """화면·검색에 보일 꼬리표(밑줄로 시작하는 가져오기 기록은 숨긴다)."""
    return {k: v for k, v in (meta or {}).items() if not str(k).startswith("_")}


def _internal_only(ctx: Ctx, kb_id: str) -> KnowledgeBase:
    from api.routers.knowledge_v08 import internal_kb

    return internal_kb(ctx, kb_id)


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
        "metadata": visible_meta(d.doc_metadata),
        "source": d.source,
        "url": d.url,
        "enabled": d.enabled,
    }


@router.post("/knowledge-bases/{kb_id}/documents")
async def upload_document(
    kb_id: str, ctx: KbBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    filename = file.filename or "document"
    mime = file.content_type or "application/octet-stream"
    if svc.kind_of(filename, mime) is None:
        raise AppError(
            415,
            "PDF·DOCX·PPTX·XLSX·HTML·TXT·MD 파일만 올릴 수 있어요.",
            "파일 형식을 바꿔서 다시 올려 주세요.",
        )
    content = await file.read(svc.MAX_UPLOAD_BYTES + 1)
    if len(content) > svc.MAX_UPLOAD_BYTES:
        raise AppError(413, "파일이 너무 커요(최대 20MB).", "파일을 나눠서 올려 주세요.")
    _internal_only(ctx, kb_id)
    kb_limits.check_write(ctx.db, ctx.workspace_id, docs=1, size=len(content))
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
    top_k: int | None = Field(default=None, ge=1, le=20)
    method: Literal["vector", "keyword", "hybrid"] | None = None
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    metadata_filter: dict[str, str] | None = None


@router.post("/knowledge-bases/{kb_id}/search")
def search(kb_id: str, body: SearchIn, ctx: KbBuilders) -> list[dict[str, Any]]:
    try:
        return svc.search(
            ctx.db,
            ctx.workspace_id,
            kb_id,
            body.query,
            body.top_k,
            method=body.method,
            score_threshold=body.score_threshold,
            metadata_filter=body.metadata_filter,
        )
    except NodeError as exc:
        raise AppError(400, exc.message, "AI 연결 설정을 확인한 뒤 다시 검색하세요.") from exc


# ---------------- v0.2 ----------------
class KbPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    settings: dict[str, Any] | None = None
    project_id: str | None = None


@router.patch("/knowledge-bases/{kb_id}")
def update_kb(kb_id: str, body: KbPatch, ctx: KbBuilders) -> dict[str, Any]:
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    if body.name:
        kb.name = body.name
    if body.settings is not None:
        try:
            svc.patch_kb_settings(kb, body.settings)
        except pipe.PipelineError as exc:
            raise AppError(422, exc.message, exc.hint) from exc
    if body.project_id is not None:
        check_project_target(ctx, kb.workspace_id, body.project_id)
        kb.project_id = body.project_id or None
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="kb.update",
        target_type="knowledge_base",
        target_id=kb.id,
    )
    ctx.db.commit()
    count = ctx.db.scalar(select(func.count(Document.id)).where(Document.kb_id == kb.id)) or 0
    return _kb(kb, count)


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/knowledge-bases/{kb_id}/documents/url")
def import_url(kb_id: str, body: UrlIn, ctx: KbBuilders) -> dict[str, Any]:
    _internal_only(ctx, kb_id)
    try:
        res = safe_http.request("GET", body.url.strip())
    except NodeError as exc:
        raise AppError(400, exc.message, "공개된 웹 페이지 주소인지 확인하세요.") from exc
    raw = res.get("body")
    if int(res.get("status", 0)) >= 400 or raw is None:
        raise AppError(
            400,
            "웹 페이지를 가져오지 못했어요.",
            "주소가 맞는지, 로그인 없이 열리는 페이지인지 확인하세요.",
        )
    page = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    title, body_text = svc.html_to_text(page)
    if len(body_text.strip()) < 20:
        raise AppError(
            422, "페이지에서 글을 거의 찾지 못했어요.", "글이 많은 다른 페이지를 써 보세요."
        )
    name = (title or body.url)[:200]
    kb_limits.check_write(ctx.db, ctx.workspace_id, docs=1, size=len(body_text.encode("utf-8")))
    doc = Document(
        kb_id=kb_id,
        filename=f"{name}.txt" if not name.endswith(".txt") else name,
        mime="text/plain",
        size=len(body_text.encode("utf-8")),
        status="uploaded",
        content=body_text.encode("utf-8"),
        source="url",
        url=body.url.strip(),
        doc_metadata={"source_url": body.url.strip()},
    )
    ctx.db.add(doc)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="kb.document_url",
        target_type="document",
        target_id=doc.id,
        meta={"url": body.url},
    )
    ctx.db.commit()
    enqueue_document(doc.id)
    ctx.db.refresh(doc)
    count = ctx.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)) or 0
    return _doc(doc, count)


class DocPatch(BaseModel):
    metadata: dict[str, str] | None = None
    # 문서 켜기·끄기(끄면 검색에서 빠짐)
    enabled: bool | None = None


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: DocPatch, ctx: DocBuilders) -> dict[str, Any]:
    doc = ctx.db.get(Document, document_id)
    if doc is None:
        raise not_found("문서")
    if body.metadata is not None:
        # 가져오기 기록(밑줄 키)은 사용자가 고친 꼬리표 목록에 없어도 남긴다
        keep = {k: v for k, v in (doc.doc_metadata or {}).items() if str(k).startswith("_")}
        doc.doc_metadata = {
            **{
                str(k)[:50]: str(v)[:200]
                for k, v in list(body.metadata.items())[:30]
                if str(k).strip() and not str(k).startswith("_")
            },
            **keep,
        }
    if body.enabled is not None:
        doc.enabled = body.enabled
        audit(
            ctx.db,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user.id,
            action="kb.document_toggle",
            target_type="document",
            target_id=doc.id,
            meta={"filename": doc.filename, "enabled": body.enabled},
        )
    ctx.db.commit()
    count = ctx.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)) or 0
    return _doc(doc, count)


@router.post("/documents/{document_id}/reprocess")
def reprocess_document(document_id: str, ctx: DocBuilders) -> dict[str, Any]:
    doc = ctx.db.get(Document, document_id)
    if doc is None:
        raise not_found("문서")
    doc.status = "uploaded"
    ctx.db.commit()
    enqueue_document(doc.id)
    ctx.db.refresh(doc)
    count = ctx.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)) or 0
    return _doc(doc, count)


DocViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="document"))]
ChunkBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="chunk"))]


def _chunk(c: Chunk) -> dict[str, Any]:
    return {
        "id": c.id,
        "index": c.position,
        "content": c.content,
        "parent_content": c.parent_content,
        "enabled": c.enabled,
        "char_count": len(c.content),
    }


@router.get("/documents/{document_id}/chunks")
def list_chunks(document_id: str, ctx: DocViewers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)
    )
    return [_chunk(c) for c in rows]


class ChunkPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    enabled: bool | None = None


@router.patch("/chunks/{chunk_id}")
def update_chunk(chunk_id: str, body: ChunkPatch, ctx: ChunkBuilders) -> dict[str, Any]:
    c = ctx.db.get(Chunk, chunk_id)
    if c is None:
        raise not_found("조각")
    if body.enabled is not None:
        c.enabled = body.enabled
    if body.content is not None and body.content != c.content:
        c.content = body.content
        try:
            svc.reembed_chunk(ctx.db, c)
        except ValueError as exc:
            raise AppError(400, "조각을 다시 임베딩하지 못했어요.", str(exc)) from exc
    ctx.db.commit()
    return _chunk(c)


# ---------------- v0.6 질문·답 형식과 문서 처리 순서 ----------------
MAX_TABLE_BYTES = 5 * 1024 * 1024
PREVIEW_CHUNKS = 50


async def _read_table_file(file: UploadFile) -> tuple[str, bytes]:
    filename = file.filename or "qa.csv"
    if not pipe.is_table(filename):
        raise AppError(
            415,
            "질문·답 표는 CSV나 XLSX 파일만 올릴 수 있어요.",
            "엑셀에서 CSV로 저장해 올려 주세요.",
        )
    content = await file.read(MAX_TABLE_BYTES + 1)
    if len(content) > MAX_TABLE_BYTES:
        raise AppError(413, "표 파일이 너무 커요(최대 5MB).", "파일을 나눠서 올려 주세요.")
    return filename, content


@router.post("/knowledge-bases/{kb_id}/qa/columns")
async def qa_columns(
    kb_id: str, ctx: KbBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """질문·답 표의 열 이름과 앞 몇 줄(어느 열이 질문·답인지 고르기 전에)."""
    del kb_id, ctx
    filename, content = await _read_table_file(file)
    try:
        return pipe.table_columns(content, filename)
    except pipe.PipelineError as exc:
        raise AppError(422, exc.message, exc.hint) from exc


@router.post("/knowledge-bases/{kb_id}/documents/qa")
async def import_qa_table(
    kb_id: str,
    ctx: KbBuilders,
    file: Annotated[UploadFile, File()],
    question_column: Annotated[str | None, Form(max_length=200)] = None,
    answer_column: Annotated[str | None, Form(max_length=200)] = None,
) -> dict[str, Any]:
    """질문·답 표 가져오기: 한 줄이 조각 하나(질문으로 찾고 답을 돌려줌)."""
    filename, content = await _read_table_file(file)
    _internal_only(ctx, kb_id)
    kb_limits.check_write(ctx.db, ctx.workspace_id, docs=1, size=len(content))
    try:
        pairs = pipe.qa_pairs_from_table(content, filename, question_column, answer_column)
        header = pipe.read_table(content, filename)[0]
    except pipe.PipelineError as exc:
        raise AppError(422, exc.message, exc.hint) from exc
    gq, ga = pipe.guess_columns(header)
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        mime="text/csv" if filename.lower().endswith(".csv") else svc.XLSX_MIME,
        size=len(content),
        status="uploaded",
        content=content,
        source=pipe.QA_SOURCE,
        doc_metadata={
            pipe.QA_Q_KEY: question_column or gq or "",
            pipe.QA_A_KEY: answer_column or ga or "",
        },
    )
    ctx.db.add(doc)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="kb.document_qa_import",
        target_type="document",
        target_id=doc.id,
        meta={"filename": filename, "rows": len(pairs)},
    )
    ctx.db.commit()
    enqueue_document(doc.id)
    ctx.db.refresh(doc)
    count = ctx.db.scalar(select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)) or 0
    return _doc(doc, count)


def _bad_settings() -> AppError:
    return AppError(422, "설정 형식이 올바르지 않아요.", "화면을 새로고침한 뒤 다시 해 보세요.")


@router.post("/knowledge-bases/{kb_id}/preview")
async def preview_pipeline(
    kb_id: str,
    ctx: KbBuilders,
    file: Annotated[UploadFile | None, File()] = None,
    document_id: Annotated[str | None, Form(max_length=64)] = None,
    settings: Annotated[str | None, Form(max_length=20000)] = None,
) -> dict[str, Any]:
    """문서 처리 순서를 저장하지 않고 돌려 본다(올린 파일 또는 이미 있는 문서)."""
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    _internal_only(ctx, kb_id)
    try:
        patch = json.loads(settings) if settings else {}
    except ValueError as exc:
        raise _bad_settings() from exc
    if not isinstance(patch, dict):
        raise _bad_settings()
    try:
        cfg = svc.merged_settings(kb, patch)
    except pipe.PipelineError as exc:
        raise AppError(422, exc.message, exc.hint) from exc
    source = "upload"
    doc_meta: dict[str, Any] = {}
    if file is not None:
        filename = file.filename or "document"
        mime = file.content_type or "application/octet-stream"
        if svc.kind_of(filename, mime) is None and not pipe.is_table(filename):
            raise AppError(
                415,
                "PDF·DOCX·PPTX·XLSX·HTML·TXT·MD·CSV 파일만 미리 볼 수 있어요.",
                "파일 형식을 바꿔서 다시 올려 주세요.",
            )
        content = await file.read(svc.MAX_UPLOAD_BYTES + 1)
        if len(content) > svc.MAX_UPLOAD_BYTES:
            raise AppError(413, "파일이 너무 커요(최대 20MB).", "파일을 나눠서 올려 주세요.")
        if filename.lower().endswith(".csv"):
            source = pipe.QA_SOURCE
    elif document_id:
        doc = ctx.db.get(Document, document_id)
        if doc is None or doc.kb_id != kb_id:
            raise not_found("문서")
        filename, mime, content = doc.filename, doc.mime, doc.content or b""
        source, doc_meta = doc.source, dict(doc.doc_metadata or {})
    else:
        raise AppError(422, "미리 볼 문서가 없어요.", "파일을 올리거나 문서를 하나 골라 주세요.")
    try:
        result = pipe.run_pipeline(
            ctx.db,
            ctx.workspace_id,
            cfg,
            filename=filename,
            mime=mime,
            content=content,
            source=source,
            doc_metadata=doc_meta,
            preview=True,
        )
    except pipe.PipelineError as exc:
        raise AppError(422, exc.message, exc.hint) from exc
    except ValueError as exc:
        raise AppError(422, str(exc), "다른 파일로 다시 해 보세요.") from exc
    finally:
        ctx.db.rollback()  # 미리 보기는 아무것도 저장하지 않는다
    return {
        "total": len(result.pieces),
        "chunks": [
            {"index": i, **p.as_dict(), "char_count": len(p.content)}
            for i, p in enumerate(result.pieces[:PREVIEW_CHUNKS])
        ],
        "metadata": result.metadata,
        "log": result.log,
        "text_preview": result.text[:2000],
        "chunk_mode": cfg["chunk_mode"],
    }


@router.post("/knowledge-bases/{kb_id}/reprocess")
def reprocess_kb(kb_id: str, ctx: KbBuilders) -> dict[str, Any]:
    """모든 문서를 지금 처리 순서로 다시 나눈다(워커에서)."""
    _internal_only(ctx, kb_id)
    docs = list(ctx.db.scalars(select(Document).where(Document.kb_id == kb_id)))
    for d in docs:
        d.status = "uploaded"
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="kb.reprocess",
        target_type="knowledge_base",
        target_id=kb_id,
        meta={"documents": len(docs)},
    )
    ctx.db.commit()
    for d in docs:
        enqueue_document(d.id)
    return {"queued": len(docs)}
