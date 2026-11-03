"""지식베이스: 문서 텍스트 추출 → 청킹 → 임베딩 → 검색."""

import html
import io
import json
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
from nodes import NodeError

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
    "retrieval": {
        "method": "vector",
        "top_k": 4,
        "score_threshold": 0.0,
        "vector_weight": 0.7,
        "rerank": False,
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
    return out


def patch_kb_settings(kb: KnowledgeBase, patch: dict[str, Any]) -> dict[str, Any]:
    cur = kb_settings(kb)
    for k, v in patch.items():
        if k == "retrieval" and isinstance(v, dict):
            cur["retrieval"].update({kk: vv for kk, vv in v.items() if kk in cur["retrieval"]})
        elif k in cur:
            cur[k] = v
    if cur["chunk_mode"] not in ("general", "parent_child"):
        cur["chunk_mode"] = "general"
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
    kb.chunk_size = cur["chunk_size"]
    kb.settings = cur
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
        content = extract_text(doc.content or b"", doc.filename, doc.mime)
        pieces = _pieces(content, kb_settings(kb))
        if not pieces:
            raise ValueError(
                "문서에서 글자를 찾지 못했어요. 스캔 이미지 PDF는 아직 지원하지 않아요."
            )
        vectors = _embed(db, kb.workspace_id, [p[0] for p in pieces], kb.embedding_model)
        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        for i, ((piece, parent), vec) in enumerate(zip(pieces, vectors, strict=True)):
            db.add(
                Chunk(
                    document_id=doc.id,
                    kb_id=kb.id,
                    content=piece,
                    parent_content=parent,
                    embedding=vec,
                    position=i,
                    enabled=True,
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


def _rerank(
    db: Session, workspace_id: str, query: str, items: list[tuple[Chunk, float]]
) -> list[tuple[Chunk, float]]:
    if len(items) < 2:
        return items
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
) -> list[dict[str, Any]]:
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None or kb.workspace_id != workspace_id:
        raise NodeError("지식베이스를 찾을 수 없어요. 단계 설정에서 다시 골라 주세요.")
    if not query.strip():
        return []
    cfg = kb_settings(kb)["retrieval"]
    method = method or str(cfg["method"])
    k = int(top_k or cfg["top_k"])
    threshold = float(cfg["score_threshold"] if score_threshold is None else score_threshold)
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
    )[: max(k, 1) * (3 if cfg["rerank"] else 1)]
    if cfg["rerank"]:
        ranked = _rerank(db, workspace_id, query, ranked)
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
                "metadata": (d.doc_metadata if d else {}) or {},
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
