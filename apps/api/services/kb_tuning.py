"""v0.8 검색 튜닝: 대표 질문 세트로 검색 설정(방식·개수·재정렬)을 비교해 가장 잘 맞는 설정을 찾는다.

- 질문마다 '이 문서(또는 이 낱말)가 찾아져야 한다'를 적어 둔다.
- 설정 조합(최대 12개)마다 맞게 찾은 비율(적중률)·평균 최고 점수·평균 걸린 시간을 계산한다.
- 검색은 방식마다 한 번만 하고(8개), 3·5·8개로 자르는 것은 같은 결과에서 계산해 호출을 아낀다.
- 재정렬은 AI를 한 번씩 더 부르므로, 켜려면 사용자가 비용을 알고 확인해야 한다.
"""

import secrets
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import Document, KnowledgeBase
from api.services import knowledge as kb_svc
from nodes import NodeError

MAX_QUESTIONS = 30
METHODS = ("vector", "keyword", "hybrid")
TOP_KS = (3, 5, 8)
RERANK_TOP_K = 5
MAX_SECONDS = 150.0
METHOD_LABEL = {"vector": "의미", "keyword": "낱말", "hybrid": "혼합"}


def tuning_of(kb: KnowledgeBase) -> dict[str, Any]:
    raw = (kb.settings or {}).get("tuning")
    data = raw if isinstance(raw, dict) else {}
    qs = data.get("questions")
    return {
        "questions": [q for q in qs if isinstance(q, dict)] if isinstance(qs, list) else [],
        "last_run": data.get("last_run") if isinstance(data.get("last_run"), dict) else None,
    }


def _save(kb: KnowledgeBase, patch: dict[str, Any]) -> None:
    cur = tuning_of(kb)
    kb.settings = {**(kb.settings or {}), "tuning": {**cur, **patch}}


def clean_questions(db: Session, kb_id: str, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """질문 목록을 확인한다(최대 30개, 질문마다 기대하는 문서나 낱말이 있어야 한다)."""
    if len(raw) > MAX_QUESTIONS:
        raise AppError(
            422,
            f"대표 질문은 {MAX_QUESTIONS}개까지 넣을 수 있어요.",
            "중요한 질문만 남기고 다시 저장하세요.",
        )
    docs = {d.id: d.filename for d in db.scalars(select(Document).where(Document.kb_id == kb_id))}
    out: list[dict[str, Any]] = []
    for i, q in enumerate(raw):
        text = str(q.get("question") or "").strip()[:300]
        word = str(q.get("expect_keyword") or "").strip()[:100]
        doc_id = str(q.get("expect_document_id") or "").strip()
        if not text:
            continue
        if doc_id and doc_id not in docs:
            raise AppError(
                422,
                f"{i + 1}번째 질문에서 고른 문서를 찾을 수 없어요.",
                "문서 목록을 새로고침한 뒤 다시 고르세요.",
            )
        if not word and not doc_id:
            raise AppError(
                422,
                f"{i + 1}번째 질문에 '찾아져야 할 문서나 낱말'이 없어요.",
                "정답이 들어 있는 문서를 고르거나 정답에 들어 있는 낱말을 적어 주세요.",
            )
        out.append(
            {
                "id": str(q.get("id") or secrets.token_hex(4))[:16],
                "question": text,
                "expect_keyword": word,
                "expect_document_id": doc_id,
            }
        )
    return out


def save_questions(kb: KnowledgeBase, questions: list[dict[str, Any]]) -> None:
    _save(kb, {"questions": questions})


def grid(include_rerank: bool) -> list[tuple[str, int, bool]]:
    combos = [(m, k, False) for m in METHODS for k in TOP_KS]
    if include_rerank:
        combos += [(m, RERANK_TOP_K, True) for m in METHODS]
    return combos


def estimate(question_count: int) -> dict[str, Any]:
    """돌리기 전에 보여 줄 호출 수 어림."""
    base_searches = question_count * len(METHODS)
    return {
        "questions": question_count,
        "combos": len(grid(False)),
        "searches": base_searches,
        # 의미·혼합 검색은 질문을 임베딩한다
        "embedding_calls": question_count * 2,
        "with_rerank": {
            "combos": len(grid(True)),
            "searches": base_searches * 2,
            "embedding_calls": question_count * 4,
            "rerank_llm_calls": question_count * len(METHODS),
        },
    }


def _matches(q: dict[str, Any], r: dict[str, Any]) -> bool:
    doc_id = str(q.get("expect_document_id") or "")
    if doc_id and str(r.get("document_id") or "") == doc_id:
        return True
    word = str(q.get("expect_keyword") or "").strip().lower()
    if word:
        hay = f"{r.get('content', '')} {r.get('matched', '')} {r.get('filename', '')}".lower()
        return word in hay
    return False


def _row(
    method: str,
    k: int,
    rerank: bool,
    runs: list[tuple[list[dict[str, Any]], float]],
    qs: list[dict[str, Any]],
) -> dict[str, Any]:
    hits = 0
    top_scores: list[float] = []
    hit_scores: list[float] = []
    for q, (results, _ms) in zip(qs, runs, strict=True):
        top = results[:k]
        top_scores.append(float(top[0]["score"]) if top else 0.0)
        found = next((r for r in top if _matches(q, r)), None)
        if found is not None:
            hits += 1
            hit_scores.append(float(found["score"]))
    n = max(len(qs), 1)
    ms = [m for _r, m in runs]
    return {
        "method": method,
        "top_k": k,
        "rerank": rerank,
        "hit_rate": round(hits / n, 4),
        "hits": hits,
        "avg_top_score": round(sum(top_scores) / n, 4),
        "avg_ms": round(sum(ms) / max(len(ms), 1), 1),
        "hit_scores": hit_scores,
    }


def run(db: Session, kb: KnowledgeBase, *, include_rerank: bool) -> dict[str, Any]:
    """모든 대표 질문을 설정 조합마다 돌려 표를 만들고 저장한다."""
    qs = tuning_of(kb)["questions"]
    if not qs:
        raise AppError(
            422, "대표 질문이 없어요.", "질문을 하나 이상 넣고 저장한 뒤 튜닝을 실행하세요."
        )
    cfg = kb_svc.kb_settings(kb)["retrieval"]
    threshold = float(cfg["score_threshold"])
    started = time.perf_counter()
    truncated = False
    # (방식, 재정렬) → 질문마다 (결과 8개, 걸린 시간 ms)
    cache: dict[tuple[str, bool], list[tuple[list[dict[str, Any]], float]]] = {}
    errors: dict[str, str] = {}
    variants = [(m, False) for m in METHODS] + (
        [(m, True) for m in METHODS] if include_rerank else []
    )
    for method, rerank in variants:
        runs: list[tuple[list[dict[str, Any]], float]] = []
        try:
            for q in qs:
                if time.perf_counter() - started > MAX_SECONDS:
                    truncated = True
                    raise TimeoutError
                t0 = time.perf_counter()
                found = kb_svc.search(
                    db,
                    kb.workspace_id,
                    kb.id,
                    str(q["question"]),
                    max(TOP_KS),
                    method=method,
                    score_threshold=threshold,
                    rerank=rerank,
                )
                runs.append((found, (time.perf_counter() - t0) * 1000))
        except NodeError as exc:
            errors[f"{method}{'+rerank' if rerank else ''}"] = exc.message
            continue
        except TimeoutError:
            break
        cache[(method, rerank)] = runs

    rows: list[dict[str, Any]] = []
    for method, k, rerank in grid(include_rerank):
        runs_for = cache.get((method, rerank))
        if runs_for is None or len(runs_for) != len(qs):
            continue
        rows.append(_row(method, k, rerank, runs_for, qs))
    if not rows:
        first = next(iter(errors.values()), "검색을 하지 못했어요.")
        raise AppError(400, first, "AI 연결과 문서 상태를 확인한 뒤 다시 실행하세요.")

    def rank_key(r: dict[str, Any]) -> tuple[float, float, float]:
        return (r["hit_rate"], r["avg_top_score"], -r["avg_ms"])

    best = max(rows, key=rank_key)
    for r in rows:
        r["is_best"] = r is best
        r["is_current"] = (
            r["method"] == cfg["method"]
            and r["top_k"] == int(cfg["top_k"])
            and r["rerank"] == bool(cfg["rerank"])
        )
    # 지금 설정은 표 조합에 없을 수 있어(예: 4개), 같은 검색 결과에서 따로 계산해 비교 기준으로 준다
    current_row: dict[str, Any] | None = None
    cur_runs = cache.get((str(cfg["method"]), bool(cfg["rerank"])))
    if cur_runs is not None and len(cur_runs) == len(qs):
        cur_k = max(1, min(int(cfg["top_k"]), max(TOP_KS)))
        current_row = _row(str(cfg["method"]), cur_k, bool(cfg["rerank"]), cur_runs, qs)
        current_row.pop("hit_scores", None)
        current_row["is_current"] = True
    hs = sorted(best["hit_scores"])
    suggested = round((hs[0] * 0.9) // 0.05 * 0.05, 2) if hs else None
    for r in rows:
        r.pop("hit_scores", None)
    result = {
        "at": datetime.now(UTC).isoformat(),
        "questions": len(qs),
        "include_rerank": include_rerank,
        "threshold": threshold,
        "rows": rows,
        "best": {k: v for k, v in best.items() if k != "hit_scores"},
        "current_row": current_row,
        "suggested_threshold": suggested,
        "errors": errors,
        "truncated": truncated,
    }
    _save(kb, {"last_run": result})
    return result
