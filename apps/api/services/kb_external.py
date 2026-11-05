"""v0.8 외부 지식베이스: 고객이 직접 운영하는 검색 서비스를 지식베이스처럼 쓴다.

Dify의 External Knowledge API와 같은 모양이다.
  POST {주소}/retrieval
  Authorization: Bearer <API 키>      (연결 정보 'HTTP 인증 정보'의 토큰)
  {"knowledge_id": "...", "query": "...", "retrieval_setting": {"top_k": 3, "score_threshold": 0.5}}
  → {"records": [{"content": "...", "score": 0.8, "title": "...", "metadata": {...}}]}
문서를 올리거나 임베딩하지 않는다. 호출은 safe_http(사설망 차단)를 거치고 키는 기록에 남기지 않는다.
"""

import time
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from api.connectors.http_auth import auth_headers
from api.core.errors import AppError
from api.engine import safe_http
from api.models import KnowledgeBase
from nodes import NodeError

MAX_RECORDS = 20
MAX_CONTENT_CHARS = 8000


def external_of(kb: KnowledgeBase) -> dict[str, Any] | None:
    """외부 지식베이스 설정(주소·지식 id·연결 정보 id). 일반 지식베이스면 None."""
    saved = kb.settings or {}
    if saved.get("kind") != "external":
        return None
    ext = saved.get("external")
    return ext if isinstance(ext, dict) else None


def clean_endpoint(raw: str) -> str:
    url = (raw or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.fragment:
        raise AppError(
            422,
            "외부 지식베이스 주소 형식이 올바르지 않아요.",
            "https://로 시작하는 서비스 주소를 넣어 주세요. 예: https://rag.example.com/api",
        )
    if url.lower().endswith("/retrieval"):
        url = url[: -len("/retrieval")]
    return url


def retrieve(
    db: Session,
    workspace_id: str,
    ext: dict[str, Any],
    query: str,
    top_k: int,
    threshold: float,
) -> list[dict[str, Any]]:
    """검색 서비스에 질문하고 받은 기록을 지식 검색 결과 모양으로 바꾼다."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    cred = str(ext.get("credential_id") or "")
    if cred:
        headers.update(auth_headers(db, workspace_id, {"type": "bearer", "credential_id": cred}))
    body = {
        "knowledge_id": str(ext.get("knowledge_id") or ""),
        "query": query,
        "retrieval_setting": {"top_k": int(top_k), "score_threshold": float(threshold)},
    }
    res = safe_http.request(
        "POST", str(ext["endpoint"]).rstrip("/") + "/retrieval", headers=headers, body=body
    )
    status = int(res.get("status", 0))
    if status in (401, 403):
        raise NodeError(
            "외부 지식베이스가 인증을 받아 주지 않았어요. API 키(연결 정보)가 맞는지 확인하세요."
        )
    if status == 404:
        raise NodeError(
            "외부 지식베이스 주소를 찾지 못했어요. 주소 끝에 /retrieval을 붙이지 않았는지 확인하세요."
        )
    if status >= 400:
        raise NodeError(
            f"외부 지식베이스가 오류로 답했어요(코드 {status}). 서비스 상태를 확인하세요."
        )
    data = res.get("body")
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise NodeError(
            "외부 지식베이스의 답 형식이 달라요. 응답에 records 목록이 있는지 확인하세요."
        )
    out: list[dict[str, Any]] = []
    for i, r in enumerate(records[:MAX_RECORDS]):
        if not isinstance(r, dict):
            continue
        content = str(r.get("content") or "")[:MAX_CONTENT_CHARS]
        if not content:
            continue
        try:
            score = float(r.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score < threshold:
            continue
        meta = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        out.append(
            {
                "chunk_id": f"ext-{i}",
                "document_id": "",
                "filename": str(r.get("title") or "외부 지식베이스"),
                "content": content,
                "matched": content,
                "score": round(score, 4),
                "metadata": meta,
                "external": True,
            }
        )
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[: max(1, int(top_k))]


def test_connection(
    db: Session, workspace_id: str, ext: dict[str, Any], query: str = "연결 시험"
) -> dict[str, Any]:
    """저장 전에 연결해 보고 결과(성공 여부·받은 기록 수·걸린 시간)를 돌려준다."""
    started = time.perf_counter()
    try:
        records = retrieve(db, workspace_id, ext, query, 3, 0.0)
    except NodeError as exc:
        return {
            "ok": False,
            "message": exc.message,
            "hint": "설정을 고친 뒤 다시 시험하세요.",
            "records": 0,
        }
    return {
        "ok": True,
        "message": f"연결됐어요. '{query}'로 {len(records)}개를 받았어요.",
        "hint": "",
        "records": len(records),
        "ms": round((time.perf_counter() - started) * 1000),
        "sample": [
            {"title": r["filename"], "score": r["score"], "content": r["content"][:160]}
            for r in records[:3]
        ],
    }
