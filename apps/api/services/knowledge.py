"""지식베이스: 문서 텍스트 추출 → 청킹 → 임베딩 → 검색."""

import html
import io
import json
import logging
import math
import re
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
from api.services import storage
from nodes import NodeError

log = logging.getLogger("genio.knowledge")

ALLOWED_MIME = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "text/x-markdown": "md",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EMBED_BATCH = 64


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALLOWED_MIME.update({DOCX_MIME: "docx", PPTX_MIME: "pptx", XLSX_MIME: "xlsx", "text/html": "html"})
# v0.9: 그림 파일(PNG·JPG·WEBP)은 '이미지 설명' 단계가 켜져 있을 때만 검색 조각이 된다
ALLOWED_MIME.update({"image/png": "image", "image/jpeg": "image", "image/webp": "image"})
EXTENSIONS = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".md": "txt",
    ".markdown": "txt",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}
MAX_SHEET_ROWS = 5000


def kind_of(filename: str, mime: str) -> str | None:
    lower = filename.lower()
    for ext, kind in EXTENSIONS.items():
        if lower.endswith(ext):
            return kind
    return ALLOWED_MIME.get(mime)


def _docx_text(content: bytes) -> str:
    import docx

    d = docx.Document(io.BytesIO(content))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def _pptx_text(content: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(content))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                texts.append(shape.text_frame.text.strip())
        if texts:
            slides.append(f"[슬라이드 {i}]\n" + "\n".join(texts))
    return "\n\n".join(slides)


def _xlsx_text(content: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = []
        for n, row in enumerate(ws.iter_rows(values_only=True)):
            if n >= MAX_SHEET_ROWS:
                break
            cells = ["" if v is None else str(v) for v in row]
            if any(c.strip() for c in cells):
                rows.append(" | ".join(cells))
        if rows:
            out.append(f"[시트 {ws.title}]\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(out)


def extract_text(content: bytes, filename: str, mime: str) -> str:
    kind = kind_of(filename, mime)
    if kind == "image":
        return ""  # 그림은 글이 없다. '이미지 설명' 단계가 그림을 글로 바꾼다.
    if kind == "pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [p.extract_text() or "" for p in reader.pages]
        except PdfReadError as exc:
            raise ValueError(
                "PDF를 읽지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인하세요."
            ) from exc
        return "\n\n".join(pages)
    try:
        if kind == "docx":
            return _docx_text(content)
        if kind == "pptx":
            return _pptx_text(content)
        if kind == "xlsx":
            return _xlsx_text(content)
    except Exception as exc:  # 손상·암호 걸린 오피스 파일
        raise ValueError(
            f"{(kind or '').upper()} 파일을 읽지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인하세요."
        ) from exc
    if kind == "html":
        title, body = html_to_text(_decode(content))
        return (title + "\n\n" + body).strip()
    return _decode(content)


def _decode(content: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def chunk_text(
    text: str, size: int = 800, overlap: int = 100, separator: str = "\n\n"
) -> list[str]:
    """문단 단위로 모아 size 글자 안팎의 조각을 만든다. 긴 문단은 잘라서 겹치게 둔다."""
    sep = separator.encode().decode("unicode_escape") if "\\" in separator else separator
    paras = [p.strip() for p in text.replace("\r\n", "\n").split(sep or "\n\n")]
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


def _fit(vec: list[float], dim: int) -> list[float]:
    """저장 칸(dim) 크기에 맞춘다. 작으면 0을 채운다(코사인 유사도는 그대로)."""
    if len(vec) == dim:
        return vec
    if len(vec) < dim:
        return [*vec, *([0.0] * (dim - len(vec)))]
    raise LlmError(
        f"이 임베딩 모델은 {len(vec)}차원이라 저장할 수 없어요(최대 {dim}).",
        "1536차원 이하 모델(text-embedding-3-small 등)을 고르세요.",
    )


def _embed(
    db: Session, workspace_id: str, texts: list[str], model: str | None = None
) -> list[list[float]]:
    """지식베이스마다 고정된 임베딩 모델(model)로 만든다. 없으면 기본 모델."""
    s = get_settings()
    llm = resolve_llm(db, workspace_id, purpose="embedding")
    use = (model or "").strip() or s.genio_embedding_model
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        vectors.extend(
            _fit(list(v), s.genio_embedding_dim)
            for v in llm.adapter.embed(model=use, texts=texts[i : i + EMBED_BATCH])
        )
    return vectors


KB_DEFAULTS: dict[str, Any] = {
    "chunk_mode": "general",
    "separator": "\\n\\n",
    "chunk_size": 800,
    "chunk_overlap": 100,
    "child_chunk_size": 200,
    # v0.6: 질문·답 형식에서 AI가 조각마다 만들 쌍 수, 문서 처리 순서(kb_pipeline)
    "qa_pairs_per_chunk": 3,
    "pipeline": None,
    # v0.8: 지식베이스 종류(internal | external), 외부 지식베이스 연결, 가져오기 소스, 검색 튜닝.
    # 이 네 가지는 전용 API로만 바꾼다(PATCH 설정에서는 무시).
    "kind": "internal",
    "external": None,
    "sources": [],
    "tuning": {"questions": [], "last_run": None},
    "retrieval": {
        "method": "vector",
        "top_k": 4,
        "score_threshold": 0.0,
        "vector_weight": 0.7,
        "rerank": False,
        # v0.9: 재정렬 전용 모델 연결(AI 연결 id)과 모델 이름. 비우면 AI(LLM)로 재정렬한다
        "rerank_connection": "",
        "rerank_model": "",
    },
}


def kb_settings(kb: KnowledgeBase) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(KB_DEFAULTS))
    out["chunk_size"] = kb.chunk_size
    saved = kb.settings or {}
    for k, v in saved.items():
        if k == "retrieval" and isinstance(v, dict):
            out["retrieval"].update({kk: vv for kk, vv in v.items() if kk in out["retrieval"]})
        elif k in out:
            out[k] = v
    from api.services.kb_pipeline import PipelineError, default_pipeline, normalize_pipeline

    try:
        out["pipeline"] = normalize_pipeline(out["pipeline"])
    except PipelineError:
        out["pipeline"] = default_pipeline()
    return out


def patch_kb_settings(kb: KnowledgeBase, patch: dict[str, Any]) -> dict[str, Any]:
    cur = merged_settings(kb, patch)
    kb.chunk_size = cur["chunk_size"]
    kb.settings = cur
    return cur


# 전용 API로만 바꾸는 설정(일반 설정 저장으로는 바꿀 수 없다)
PROTECTED_KEYS = ("kind", "external", "sources", "tuning")


def merged_settings(kb: KnowledgeBase, patch: dict[str, Any]) -> dict[str, Any]:
    """저장하지 않고 patch를 더한 설정(미리 보기에도 쓴다). 잘못된 정규식은 PipelineError."""
    cur = kb_settings(kb)
    for k, v in patch.items():
        if k in PROTECTED_KEYS:
            continue
        if k == "retrieval" and isinstance(v, dict):
            cur["retrieval"].update({kk: vv for kk, vv in v.items() if kk in cur["retrieval"]})
        elif k in cur:
            cur[k] = v
    if cur["chunk_mode"] not in ("general", "parent_child", "qa"):
        cur["chunk_mode"] = "general"
    from api.services.kb_pipeline import normalize_pipeline

    cur["pipeline"] = normalize_pipeline(cur["pipeline"])  # 잘못된 정규식은 PipelineError
    cur["qa_pairs_per_chunk"] = max(1, min(int(cur["qa_pairs_per_chunk"] or 3), 10))
    cur["chunk_size"] = max(200, min(int(cur["chunk_size"]), 4000))
    cur["chunk_overlap"] = max(0, min(int(cur["chunk_overlap"]), cur["chunk_size"] // 2))
    cur["child_chunk_size"] = max(50, min(int(cur["child_chunk_size"]), cur["chunk_size"]))
    r = cur["retrieval"]
    if r["method"] not in ("vector", "keyword", "hybrid"):
        r["method"] = "vector"
    r["top_k"] = max(1, min(int(r["top_k"]), 20))
    r["score_threshold"] = max(0.0, min(float(r["score_threshold"]), 1.0))
    r["vector_weight"] = max(0.0, min(float(r["vector_weight"]), 1.0))
    r["rerank"] = bool(r["rerank"])
    r["rerank_connection"] = str(r.get("rerank_connection") or "").strip()[:36]
    r["rerank_model"] = str(r.get("rerank_model") or "").strip()[:100]
    return cur


def _pieces(text: str, cfg: dict[str, Any]) -> list[tuple[str, str | None]]:
    """(검색에 쓸 조각, 돌려줄 부모 문단) 목록."""
    parents = chunk_text(
        text,
        size=int(cfg["chunk_size"]),
        overlap=int(cfg["chunk_overlap"]),
        separator=str(cfg["separator"]),
    )
    if cfg["chunk_mode"] != "parent_child":
        return [(p, None) for p in parents]
    out: list[tuple[str, str | None]] = []
    size = int(cfg["child_chunk_size"])
    for parent in parents:
        # Dify처럼 줄·문장마다 자식 조각 하나. 너무 긴 문장만 크기대로 자른다.
        for sent in (s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", parent)):
            while len(sent) > size:
                out.append((sent[:size], parent))
                sent = sent[size:].strip()
            if sent:
                out.append((sent, parent))
    return out


def process_document(db: Session, document_id: str) -> None:
    """문서 처리 순서(v0.6 kb_pipeline)대로 꺼내기 → 정리 → 나누기 → (번역·요약) → 꼬리표 → (이미지 설명) → 저장."""
    from api.services import kb_images
    from api.services.kb_pipeline import PipelineError, run_pipeline

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
        result = run_pipeline(
            db,
            kb.workspace_id,
            kb_settings(kb),
            filename=doc.filename,
            mime=doc.mime,
            content=storage.read_content(doc),
            source=doc.source,
            doc_metadata=doc.doc_metadata,
        )
        pieces = result.pieces
        if not pieces:
            raise ValueError(
                "문서에서 글자를 찾지 못했어요. 스캔 이미지 PDF는 '이미지 설명'을 켜면 읽어 볼 수 있어요."
            )
        vectors = _embed(db, kb.workspace_id, [p.content for p in pieces], kb.embedding_model)
        # 새 결과가 준비된 뒤에야 예전 조각·그림을 지운다(실패하면 예전 것이 남는다)
        old_images = kb_images.delete_document_images(db, doc)
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        image_ids: list[str] = []
        image_files: dict[int, str] = {}
        for n, img in enumerate(result.images):
            f = kb_images.store_image(
                db, kb.workspace_id, kb_images.image_file_name(kb.id, doc.id, n, img), img
            )
            image_files[n] = f.id
            image_ids.append(f.id)
        for i, (piece, vec) in enumerate(zip(pieces, vectors, strict=True)):
            meta: dict[str, Any] = {"index": i, "filename": doc.filename}
            if piece.question is not None:
                meta.update({"qa": True, "question": piece.question, "answer": piece.answer})
            if piece.kind == "image" and piece.image_index is not None:
                meta.update(
                    {
                        "kind": "image",
                        "file_id": image_files.get(piece.image_index),
                        "caption": piece.caption,
                        "page": piece.page,
                    }
                )
            db.add(
                Chunk(
                    document_id=doc.id,
                    kb_id=kb.id,
                    content=piece.content,
                    parent_content=piece.parent,
                    embedding=vec,
                    position=i,
                    enabled=True,
                    metadata_=meta,
                )
            )
        extra: dict[str, Any] = {}
        if image_ids:
            extra[kb_images.IMG_META_KEY] = image_ids
        if result.image_report:
            extra[kb_images.IMG_REPORT_KEY] = result.image_report
        if result.usage:
            extra["_ai_usage"] = {
                "calls": len(result.usage),
                "input_tokens": sum(u[1] for u in result.usage),
                "output_tokens": sum(u[2] for u in result.usage),
            }
        doc.doc_metadata = {**(doc.doc_metadata or {}), **result.metadata, **extra}
        doc.status = "ready"
        db.commit()
        storage.purge(old_images)
    except LlmError as exc:
        db.rollback()
        doc.status = "failed"
        doc.error = f"{exc.message} {exc.hint}"
        db.commit()
    except (ValueError, PipelineError) as exc:
        db.rollback()
        doc.status = "failed"
        doc.error = str(exc)
        db.commit()


def reembed_chunk(db: Session, chunk: Chunk) -> None:
    kb = db.get(KnowledgeBase, chunk.kb_id)
    if kb is None:
        return
    try:
        chunk.embedding = _embed(db, kb.workspace_id, [chunk.content], kb.embedding_model)[0]
    except LlmError as exc:
        raise ValueError(f"{exc.message} {exc.hint}") from exc


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _terms(text: str) -> set[str]:
    words = [w for w in re.findall(r"[0-9A-Za-z가-힣]+", text.lower()) if len(w) >= 2]
    grams = {w[i : i + 2] for w in words for i in range(len(w) - 1)}
    return set(words) | grams


def keyword_score(query_terms: set[str], content: str) -> float:
    if not query_terms:
        return 0.0
    ct = _terms(content)
    return len(query_terms & ct) / len(query_terms)


def _allowed_docs(
    db: Session, kb_id: str, metadata_filter: dict[str, Any] | None
) -> dict[str, Document]:
    # 꺼 둔 문서는 검색에서 뺀다(기능 정의서 §3 문서별 활성/비활성)
    docs = {
        d.id: d
        for d in db.scalars(
            select(Document).where(Document.kb_id == kb_id, Document.enabled.is_(True))
        )
    }
    if not metadata_filter:
        return docs
    want = {str(k): str(v) for k, v in metadata_filter.items() if str(k).strip()}
    return {
        i: d
        for i, d in docs.items()
        if all(str((d.doc_metadata or {}).get(k, "")) == v for k, v in want.items())
    }


def _dedicated_rerank(
    db: Session,
    workspace_id: str,
    connection_id: str,
    model: str,
    query: str,
    items: list[tuple[Chunk, float]],
) -> tuple[list[tuple[Chunk, float]], dict[str, float]] | None:
    """재정렬 전용 모델(v0.9). 연결이 없거나 호출이 실패하면 None → AI(LLM) 재정렬로 이어 간다."""
    from api.llm.rerank import rerank_documents
    from api.models import LlmProvider

    row = db.get(LlmProvider, connection_id)
    if row is None or row.workspace_id != workspace_id:
        return None
    try:
        ranked_idx = rerank_documents(row, model, query, [c.content for c, _ in items])
    except LlmError as exc:
        log.warning("재정렬 전용 모델 호출 실패(kb 검색, %s)", exc.message)
        return None
    seen = {r.index for r in ranked_idx}
    order = [r.index for r in ranked_idx] + [i for i in range(len(items)) if i not in seen]
    scores = {items[r.index][0].id: round(r.score, 4) for r in ranked_idx}
    return [items[i] for i in order], scores


def _rerank(
    db: Session,
    workspace_id: str,
    query: str,
    items: list[tuple[Chunk, float]],
    *,
    connection_id: str = "",
    model: str = "",
) -> tuple[list[tuple[Chunk, float]], dict[str, float]]:
    """(다시 줄 세운 목록, 조각별 재정렬 점수). 점수는 재정렬 전용 모델을 썼을 때만 있다."""
    if len(items) < 2:
        return items, {}
    if connection_id:
        done = _dedicated_rerank(db, workspace_id, connection_id, model, query, items)
        if done is not None:
            return done
    return _llm_rerank(db, workspace_id, query, items), {}


def _llm_rerank(
    db: Session, workspace_id: str, query: str, items: list[tuple[Chunk, float]]
) -> list[tuple[Chunk, float]]:
    listing = "\n".join(f"[{i}] {c.content[:300]}" for i, (c, _) in enumerate(items))
    try:
        llm = resolve_llm(db, workspace_id, "default")
        res = llm.adapter.complete(
            model=llm.model,
            system="질문에 답하는 데 도움이 되는 순서대로 조각 번호를 나열하세요.",
            prompt=f"질문: {query}\n\n조각:\n{listing}",
            temperature=None,
            json_schema={
                "type": "object",
                "properties": {"order": {"type": "array", "items": {"type": "integer"}}},
                "required": ["order"],
            },
        )
    except LlmError:
        return items
    order = [
        i for i in (res.data or {}).get("order", []) if isinstance(i, int) and 0 <= i < len(items)
    ]
    seen: set[int] = set()
    ranked = []
    for i in order + list(range(len(items))):
        if i not in seen:
            seen.add(i)
            ranked.append(items[i])
    return ranked


def search(
    db: Session,
    workspace_id: str,
    kb_id: str,
    query: str,
    top_k: int | None = None,
    *,
    method: str | None = None,
    score_threshold: float | None = None,
    metadata_filter: dict[str, Any] | None = None,
    rerank: bool | None = None,
) -> list[dict[str, Any]]:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None or kb.workspace_id != workspace_id:
        raise NodeError("지식베이스를 찾을 수 없어요. 단계 설정에서 다시 골라 주세요.")
    if not query.strip():
        return []
    full = kb_settings(kb)
    cfg = full["retrieval"]
    method = method or str(cfg["method"])
    k = int(top_k or cfg["top_k"])
    threshold = float(cfg["score_threshold"] if score_threshold is None else score_threshold)
    if full["kind"] == "external":
        from api.services.kb_external import retrieve

        ext = full["external"]
        if not isinstance(ext, dict):
            raise NodeError(
                "외부 지식베이스 연결 정보가 없어요. 지식베이스 설정을 다시 확인하세요."
            )
        return retrieve(db, workspace_id, ext, query, k, threshold)
    use_rerank = bool(cfg["rerank"]) if rerank is None else bool(rerank)
    weight = float(cfg["vector_weight"])
    docs = _allowed_docs(db, kb_id, metadata_filter)
    if not docs:
        return []
    doc_ids = list(docs)
    pool = max(k * 4, 20)
    scores: dict[str, float] = {}
    chunk_by_id: dict[str, Chunk] = {}
    vec_scores: dict[str, float] = {}
    if method in ("vector", "hybrid"):
        try:
            qvec = _embed(db, workspace_id, [query], kb.embedding_model)[0]
        except LlmError as exc:
            raise NodeError(f"{exc.message} {exc.hint}") from exc
        if is_postgres():
            # ivfflat는 근사 검색이라 목록을 여러 개 살펴봐야 작은 지식베이스에서도 놓치지 않는다
            db.execute(text("SET LOCAL ivfflat.probes = 10"))
            dist = Chunk.embedding.cosine_distance(qvec)
            result = db.execute(
                select(Chunk, dist.label("dist"))
                .where(
                    Chunk.kb_id == kb_id,
                    Chunk.embedding.is_not(None),
                    Chunk.enabled.is_(True),
                    Chunk.document_id.in_(doc_ids),
                )
                .order_by(dist)
                .limit(pool)
            ).all()
            for c, d in result:
                chunk_by_id[c.id] = c
                vec_scores[c.id] = 1.0 - float(d)
        else:
            for c in db.scalars(
                select(Chunk).where(
                    Chunk.kb_id == kb_id, Chunk.enabled.is_(True), Chunk.document_id.in_(doc_ids)
                )
            ):
                chunk_by_id[c.id] = c
                vec_scores[c.id] = _cosine(qvec, list(c.embedding or []))
    kw_scores: dict[str, float] = {}
    if method in ("keyword", "hybrid"):
        qt = _terms(query)
        for c in db.scalars(
            select(Chunk).where(
                Chunk.kb_id == kb_id, Chunk.enabled.is_(True), Chunk.document_id.in_(doc_ids)
            )
        ):
            sc = keyword_score(qt, c.content)
            if sc > 0:
                chunk_by_id[c.id] = c
                kw_scores[c.id] = sc
    for cid in chunk_by_id:
        if method == "vector":
            scores[cid] = vec_scores.get(cid, 0.0)
        elif method == "keyword":
            scores[cid] = kw_scores.get(cid, 0.0)
        else:
            v = vec_scores.get(cid)
            if (
                v is None
                and chunk_by_id[cid].embedding is not None
                and method == "hybrid"
                and vec_scores
            ):
                v = 0.0
            scores[cid] = weight * (v or 0.0) + (1 - weight) * kw_scores.get(cid, 0.0)
    ranked = sorted(
        ((chunk_by_id[c], s) for c, s in scores.items() if s >= threshold),
        key=lambda x: x[1],
        reverse=True,
    )[: max(k, 1) * (3 if use_rerank else 1)]
    rerank_scores: dict[str, float] = {}
    if use_rerank:
        ranked, rerank_scores = _rerank(
            db,
            workspace_id,
            query,
            ranked,
            connection_id=str(cfg.get("rerank_connection") or ""),
            model=str(cfg.get("rerank_model") or ""),
        )
    ranked = ranked[:k]
    out = []
    for c, score in ranked:
        d = docs.get(c.document_id)
        out.append(
            {
                "chunk_id": c.id,
                "document_id": c.document_id,
                "filename": d.filename if d else "",
                "content": c.parent_content or c.content,
                "matched": c.content,
                "score": round(score, 4),
                **({"rerank_score": rerank_scores[c.id]} if c.id in rerank_scores else {}),
                "metadata": {
                    k: v
                    for k, v in ((d.doc_metadata if d else {}) or {}).items()
                    if not str(k).startswith("_")
                },
                **(
                    {"question": c.metadata_.get("question"), "answer": c.metadata_.get("answer")}
                    if (c.metadata_ or {}).get("qa")
                    else {}
                ),
                **(
                    {
                        "kind": "image",
                        "image": {
                            "file_id": c.metadata_.get("file_id"),
                            "caption": c.metadata_.get("caption"),
                            "page": c.metadata_.get("page"),
                            "kb_id": c.kb_id,
                        },
                    }
                    if (c.metadata_ or {}).get("kind") == "image" and c.metadata_.get("file_id")
                    else {}
                ),
            }
        )
    return out


def html_to_text(raw: str) -> tuple[str, str]:
    """(제목, 본문 글)"""
    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    body = re.sub(r"(?is)<(head|script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", " ", raw)
    body = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html.unescape(body)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()]
    text_out = "\n".join(ln for ln in lines if ln)
    text_out = re.sub(r"\n{3,}", "\n\n", text_out)
    return title, text_out
