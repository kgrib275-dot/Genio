"""재정렬 전용 모델(v0.9): 지식 검색 결과를 질문과의 관련도로 다시 줄 세운다.

공급자(연결의 provider 값)와 호출 모양:
- cohere-rerank : POST {base}/v2/rerank   {model, query, documents[str], top_n}     → {results:[{index, relevance_score}]}
- jina-rerank   : POST {base}/v1/rerank   {model, query, documents[str], top_n}     → {results:[{index, relevance_score}]}
- voyage-rerank : POST {base}/v1/rerank   {model, query, documents[str], top_k}     → {data:[{index, relevance_score}]}
- rerank-compatible : 사용자가 정한 주소의 /rerank (Cohere 형식, vLLM·사내 서버용)
응답은 results/data, relevance_score/score 이름을 모두 읽는다(공급자마다·버전마다 조금씩 달라서).
키는 헤더로만 보내고 오류 글·기록에 넣지 않는다. 키가 여러 개면 한도에 걸릴 때 다음 키로 넘어간다.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from api.llm import keypool
from api.llm.base import KIND_AUTH, KIND_OUTAGE, KIND_RATE_LIMIT, LlmError
from api.llm.presets import PRESETS, is_rerank
from api.models import LlmProvider

log = logging.getLogger("genio.llm.rerank")

TIMEOUT = 30.0
MAX_DOCS = 100
MAX_DOC_CHARS = 2000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_KEY_ATTEMPTS = 5


@dataclass(frozen=True)
class Ranked:
    index: int
    score: float


def endpoint(provider: str, base_url: str | None) -> str:
    preset = PRESETS.get(provider)
    base = (base_url or (preset.base_url if preset else None) or "").strip().rstrip("/")
    if not base:
        raise LlmError(
            "재정렬 서버 주소가 없어요.", "AI 연결에 주소(예: http://서버:8000/v1)를 넣어 주세요."
        )
    if provider == "cohere-rerank":
        return base if base.endswith("/rerank") else f"{base}/v2/rerank"
    if provider in ("jina-rerank", "voyage-rerank"):
        return base if base.endswith("/rerank") else f"{base}/v1/rerank"
    return base if base.endswith("rerank") else f"{base}/rerank"


def request_body(
    provider: str, model: str, query: str, docs: list[str], top_n: int
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "query": query,
        "documents": [d[:MAX_DOC_CHARS] for d in docs[:MAX_DOCS]],
    }
    body["top_k" if provider == "voyage-rerank" else "top_n"] = max(1, min(top_n, len(docs)))
    return body


def _http_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
    """시험에서 바꿔 끼우는 전송 함수."""
    return httpx.post(url, headers=headers, json=body, timeout=TIMEOUT, follow_redirects=False)


def _fail(status: int) -> LlmError:
    if status in (401, 403):
        return LlmError(
            "재정렬 모델 키가 올바르지 않아요.",
            "관리 > AI 모델에서 재정렬 연결의 키를 다시 확인하세요.",
            kind=KIND_AUTH,
        )
    if status == 429:
        return LlmError(
            "재정렬 모델 요청이 너무 많아요.",
            "잠시 후 다시 시도하거나 키를 더 추가하세요.",
            retryable=True,
            kind=KIND_RATE_LIMIT,
        )
    if status == 404:
        return LlmError(
            "재정렬 모델이나 주소를 찾지 못했어요.",
            "AI 연결의 주소와 모델 이름을 확인하세요.",
        )
    if status >= 500:
        return LlmError(
            "재정렬 서버에서 오류가 났어요.",
            "잠시 후 다시 시도하세요.",
            retryable=True,
            kind=KIND_OUTAGE,
        )
    return LlmError(
        "재정렬 모델이 요청을 받아들이지 않았어요.",
        "모델 이름과 문서 길이를 확인하세요.",
    )


def parse_response(data: Any, count: int) -> list[Ranked]:
    items = data.get("results") if isinstance(data, dict) else None
    if items is None and isinstance(data, dict):
        items = data.get("data")
    if items is None and isinstance(data, list):
        items = data
    if not isinstance(items, list):
        raise LlmError(
            "재정렬 모델의 답을 읽지 못했어요.", "주소가 재정렬 API 주소인지 확인하세요."
        )
    out: list[Ranked] = []
    seen: set[int] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        idx = it.get("index")
        score = it.get("relevance_score", it.get("score"))
        if (
            isinstance(idx, int)
            and not isinstance(idx, bool)
            and 0 <= idx < count
            and idx not in seen
            and isinstance(score, int | float)
        ):
            seen.add(idx)
            out.append(Ranked(idx, float(score)))
    if not out:
        raise LlmError(
            "재정렬 모델의 답을 읽지 못했어요.", "주소가 재정렬 API 주소인지 확인하세요."
        )
    out.sort(key=lambda r: r.score, reverse=True)
    return out


def call(
    provider: str,
    api_key: str,
    base_url: str | None,
    model: str,
    query: str,
    docs: list[str],
    top_n: int | None = None,
) -> list[Ranked]:
    """재정렬 한 번. 관련도가 높은 순서로 (원래 번호, 점수)를 돌려준다."""
    url = endpoint(provider, base_url)
    body = request_body(provider, model, query, docs, top_n or len(docs))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = _http_post(url, headers, body)
    except httpx.TimeoutException:
        raise LlmError(
            "재정렬 서버가 제때 답하지 않았어요.",
            "잠시 후 다시 시도하세요.",
            retryable=True,
            kind=KIND_OUTAGE,
        ) from None
    except httpx.HTTPError:
        raise LlmError(
            "재정렬 서버에 연결하지 못했어요.",
            "주소와 네트워크를 확인하세요.",
            retryable=True,
            kind=KIND_OUTAGE,
        ) from None
    if resp.status_code >= 400:
        raise _fail(resp.status_code)
    if len(resp.content) > MAX_RESPONSE_BYTES:
        raise LlmError("재정렬 모델의 답이 너무 커요.", "문서 수를 줄여 다시 시도하세요.")
    try:
        data = resp.json()
    except ValueError:
        raise LlmError(
            "재정렬 모델의 답을 읽지 못했어요.", "주소가 재정렬 API 주소인지 확인하세요."
        ) from None
    return parse_response(data, min(len(docs), MAX_DOCS))


def rerank_documents(
    row: LlmProvider, model: str, query: str, docs: list[str], top_n: int | None = None
) -> list[Ranked]:
    """연결(row)의 키를 돌려 가며 재정렬한다. 한도·키 오류면 다음 키로 넘어간다."""
    from api.llm.registry import key_refs

    if not is_rerank(row.provider):
        raise LlmError("재정렬 전용 연결이 아니에요.", "관리 > AI 모델에서 재정렬 연결을 고르세요.")
    use = model or row.default_model
    keys = keypool.order(row.id, key_refs(row), row.key_strategy or "failover")
    if not keys:
        raise LlmError(
            "사용할 수 있는 키가 없어요.",
            "관리 > AI 모델에서 키를 켜거나 새로 추가하세요.",
            kind=KIND_AUTH,
        )
    last: LlmError | None = None
    for key in keys[:MAX_KEY_ATTEMPTS]:
        try:
            out = call(row.provider, key.secret, row.base_url, use, query, docs, top_n)
        except LlmError as exc:
            keypool.record(row.id, key.id, ok=False, error=exc.message)
            last = exc
            if exc.kind == KIND_RATE_LIMIT:
                keypool.set_cooldown(row.id, key.id, keypool.COOLDOWN_RATE_LIMIT)
            elif exc.kind == KIND_AUTH:
                keypool.set_cooldown(row.id, key.id, keypool.COOLDOWN_AUTH)
            else:
                raise
            continue
        keypool.record(row.id, key.id, ok=True)
        return out
    raise last or LlmError("재정렬에 실패했어요.", "잠시 후 다시 시도하세요.")


def probe(provider: str, api_key: str, base_url: str | None, model: str) -> LlmError | None:
    """'연결 테스트': 문서 두 개로 한 번 재정렬해 본다. 성공하면 None, 아니면 두 줄 오류."""
    try:
        call(
            provider,
            api_key,
            base_url,
            model,
            "과일",
            ["사과는 맛있는 과일이에요.", "자동차는 길 위를 달려요."],
            2,
        )
    except LlmError as exc:
        return exc
    return None
