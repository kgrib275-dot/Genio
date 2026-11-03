"""지식베이스: 문서 텍스트 추출 → 청킹 → 임베딩 → 검색."""

import io
import math
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import is_postgres
from api.llm.base import LlmError
from api.llm.registry import resolve_llm
from api.models import Chunk, Document, KnowledgeBase
from nodes import NodeError

ALLOWED_MIME = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EMBED_BATCH = 64


def kind_of(filename: str, mime: str) -> str | None:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".txt", ".md", ".markdown")):
        return "txt"
    return ALLOWED_MIME.get(mime)


def extract_text(content: bytes, filename: str, mime: str) -> str:
    kind = kind_of(filename, mime)
    if kind == "pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [p.extract_text() or "" for p in reader.pages]
        except PdfReadError as exc:
            raise ValueError(
                "PDF를 읽지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인하세요."
            ) from exc
        return "\n\n".join(pages)
    for enc in ("utf-8", "cp949"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """문단 단위로 모아 size 글자 안팎의 조각을 만든다. 긴 문단은 잘라서 겹치게 둔다."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    paras = [" ".join(p.split()) for p in paras if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        while len(p) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(p[:size])
            p = p[size - overlap :]
        if len(buf) + len(p) + 1 > size and buf:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + " " + p).strip()
        else:
            buf = (buf + "\n" + p).strip()
    if buf:
        chunks.append(buf)
    return chunks


def _embed(db: Session, workspace_id: str, texts: list[str]) -> list[list[float]]:
    s = get_settings()
    llm = resolve_llm(db, workspace_id, purpose="embedding")
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        vectors.extend(
            llm.adapter.embed(model=s.genio_embedding_model, texts=texts[i : i + EMBED_BATCH])
        )
    return vectors


def process_document(db: Session, document_id: str) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        return
    kb = db.get(KnowledgeBase, doc.kb_id)
    if kb is None:
        return
    doc.status = "processing"
    doc.error = None
    db.commit()
    try:
        text = extract_text(doc.content or b"", doc.filename, doc.mime)
        pieces = chunk_text(text, size=kb.chunk_size)
        if not pieces:
            raise ValueError(
                "문서에서 글자를 찾지 못했어요. 스캔 이미지 PDF는 아직 지원하지 않아요."
            )
        vectors = _embed(db, kb.workspace_id, pieces)
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True)):
            db.add(
                Chunk(
                    document_id=doc.id,
                    kb_id=kb.id,
                    content=piece,
                    embedding=vec,
                    metadata_={"index": i, "filename": doc.filename},
                )
            )
        doc.status = "ready"
        db.commit()
    except LlmError as exc:
        db.rollback()
        doc.status = "failed"
        doc.error = f"{exc.message} {exc.hint}"
        db.commit()
    except ValueError as exc:
        db.rollback()
        doc.status = "failed"
        doc.error = str(exc)
        db.commit()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(
    db: Session, workspace_id: str, kb_id: str, query: str, top_k: int = 4
) -> list[dict[str, Any]]:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None or kb.workspace_id != workspace_id:
        raise NodeError("지식베이스를 찾을 수 없어요. 노드 설정에서 다시 골라 주세요.")
    if not query.strip():
        return []
    try:
        qvec = _embed(db, workspace_id, [query])[0]
    except LlmError as exc:
        raise NodeError(f"{exc.message} {exc.hint}") from exc
    rows: list[tuple[Chunk, float]]
    if is_postgres():
        # ivfflat는 근사 검색이라 목록을 여러 개 살펴봐야 작은 지식베이스에서도 놓치지 않는다
        db.execute(text("SET LOCAL ivfflat.probes = 10"))
        dist = Chunk.embedding.cosine_distance(qvec)
        result = db.execute(
            select(Chunk, dist.label("dist"))
            .where(Chunk.kb_id == kb_id, Chunk.embedding.is_not(None))
            .order_by(dist)
            .limit(top_k)
        ).all()
        rows = [(c, 1.0 - float(d)) for c, d in result]
    else:
        chunks = list(db.scalars(select(Chunk).where(Chunk.kb_id == kb_id)))
        scored = [(c, _cosine(qvec, list(c.embedding or []))) for c in chunks]
        rows = sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]
    docs = {d.id: d.filename for d in db.scalars(select(Document).where(Document.kb_id == kb_id))}
    return [
        {
            "chunk_id": c.id,
            "document_id": c.document_id,
            "filename": docs.get(c.document_id, ""),
            "content": c.content,
            "score": round(score, 4),
        }
        for c, score in rows
    ]
