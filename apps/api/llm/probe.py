"""AI 연결 테스트(v0.6): 키로 공급자의 모델 목록 API를 불러 본다.

- 성공하면 그 키로 쓸 수 있는 모델 목록을 돌려준다(화면의 '기본 모델' 목록을 채움).
- 키는 요청 헤더(또는 Google은 쿼리)로만 쓰고, 오류 문장·로그에 넣지 않는다.
- 사내 서버(OpenAI 호환 직접 입력)는 사설 주소일 수 있어 AI 호출과 같은 규칙(제한 없음)을 따른다.
"""

import logging
from typing import Any

import httpx

from api.llm.base import LlmError
from api.llm.openai_adapter import azure_endpoint
from api.llm.presets import preset_base_url

log = logging.getLogger("genio.llm.probe")
TIMEOUT = 10.0
MAX_MODELS = 300

# Google 모델 목록에서 대화 생성에 쓸 수 없는 것(임베딩 등)은 뺀다
_GOOGLE_METHOD = "generateContent"
# OpenAI 목록에는 음성·이미지 생성 모델도 섞여 있어 대화용 이름만 남긴다
_OPENAI_SKIP = (
    "whisper",
    "tts",
    "dall-e",
    "davinci",
    "babbage",
    "moderation",
    "audio",
    "realtime",
    "transcribe",
    "image",
    "embedding",
    "search",
)


def _get(url: str, headers: dict[str, str], params: dict[str, str] | None = None) -> Any:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as c:
            r = c.get(url, headers=headers, params=params)
    except httpx.TimeoutException:
        raise LlmError(
            "AI 서비스가 10초 안에 답하지 않았어요.", "주소가 맞는지, 잠시 뒤 다시 시험해 보세요."
        ) from None
    except httpx.HTTPError:
        raise LlmError(
            "AI 서비스에 접속하지 못했어요.", "주소(base URL)와 인터넷 연결을 확인하세요."
        ) from None
    if r.status_code in (401, 403):
        raise LlmError("API 키가 맞지 않거나 권한이 없어요.", "키를 다시 복사해 넣어 보세요.")
    if r.status_code == 404:
        raise LlmError(
            "모델 목록 주소를 찾지 못했어요.",
            "주소(base URL) 끝에 /v1 같은 경로가 맞는지 확인하세요.",
        )
    if r.status_code >= 400:
        raise LlmError(
            f"AI 서비스가 오류로 답했어요(코드 {r.status_code}).",
            "잠시 뒤 다시 시험하거나 공급자 상태를 확인하세요.",
        )
    try:
        return r.json()
    except ValueError:
        raise LlmError(
            "AI 서비스의 답을 읽지 못했어요.", "주소가 AI 서비스의 API 주소인지 확인하세요."
        ) from None


def _openai_like(
    base: str, api_key: str, headers: dict[str, str] | None = None
) -> list[dict[str, str]]:
    data = _get(base.rstrip("/") + "/models", headers or {"Authorization": f"Bearer {api_key}"})
    items = data.get("data") if isinstance(data, dict) else data
    out = []
    for m in items or []:
        mid = str((m or {}).get("id") or "") if isinstance(m, dict) else ""
        if mid and not any(s in mid.lower() for s in _OPENAI_SKIP):
            out.append({"model": mid, "label": mid})
    return out


def list_models(provider: str, api_key: str, base_url: str | None) -> list[dict[str, str]]:
    """키로 쓸 수 있는 대화 모델 목록. 실패하면 LlmError(두 줄 문장)."""
    key = api_key.strip()
    if provider == "anthropic":
        data = _get(
            (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/models",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"limit": "1000"},
        )
        models = [
            {"model": str(m.get("id")), "label": str(m.get("display_name") or m.get("id"))}
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]
    elif provider == "google":
        data = _get(
            (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
            + "/v1beta/models",
            {"x-goog-api-key": key},
            {"pageSize": "1000"},
        )
        models = [
            {
                "model": str(m.get("name", "")).removeprefix("models/"),
                "label": str(m.get("displayName") or m.get("name")),
            }
            for m in (data.get("models") or [])
            if isinstance(m, dict) and _GOOGLE_METHOD in (m.get("supportedGenerationMethods") or [])
        ]
    elif provider == "azure":
        endpoint, version = azure_endpoint(base_url or "")
        data = _get(endpoint + "openai/models", {"api-key": key}, {"api-version": version})
        models = [
            {"model": str(m.get("id")), "label": str(m.get("id"))}
            for m in (data.get("data") or [])
            if isinstance(m, dict) and m.get("id")
        ]
    else:
        base = (
            base_url
            or preset_base_url(provider)
            or ("https://api.openai.com/v1" if provider == "openai" else None)
        )
        if not base:
            raise LlmError("주소(base URL)가 필요해요.", "예: https://api.example.com/v1")
        models = _openai_like(base, key)
    seen: set[str] = set()
    uniq = []
    for m in models:
        if m["model"] and m["model"] not in seen:
            seen.add(m["model"])
            uniq.append(m)
    uniq.sort(key=lambda m: m["model"])
    return uniq[:MAX_MODELS]
