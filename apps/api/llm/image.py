"""이미지 만들기(v0.9): OpenAI 호환(Azure 포함) 이미지 API 어댑터가 쓰는 값과 오류 번역.

어댑터는 공급자가 돌려준 그림을 가공 없이(b64 또는 주소) 넘기고, 받기·검사·저장은
services/image_gen.py가 한다. Google Imagen은 요청 형식을 문서로 확인하지 못해 지원하지 않는다.
"""

from dataclasses import dataclass, field
from typing import Any

import openai

from api.llm.base import LlmError

# 사용자가 고르는 크기(가로x세로)
SIZES = ("1024x1024", "1536x1024", "1024x1536")
MAX_COUNT = 4


@dataclass
class RawImage:
    b64: str | None = None
    url: str | None = None
    revised_prompt: str | None = None


@dataclass
class RawImageResult:
    images: list[RawImage] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def native_size(model: str, size: str) -> str:
    """모델이 받는 크기로 바꾼다(dall-e-3는 1792 크기를 쓴다)."""
    if model.lower().startswith("dall-e-3"):
        return {"1536x1024": "1792x1024", "1024x1536": "1024x1792"}.get(size, size)
    if model.lower().startswith("dall-e-2"):
        return "1024x1024"
    return size


def one_image_per_call(model: str) -> bool:
    """dall-e-3는 한 번에 한 장만 만든다(n=1)."""
    return model.lower().startswith("dall-e-3")


def map_image_error(exc: Exception) -> LlmError:
    text = str(exc).lower()
    code = str(getattr(exc, "code", "") or "").lower()
    if isinstance(exc, openai.BadRequestError):
        if "content_policy" in code or "moderation" in code or "safety" in text:
            return LlmError(
                "이미지 만들기 요청이 AI의 안전 규칙에 걸렸어요.",
                "표현을 바꾸거나 사람·상표·폭력 같은 내용을 빼고 다시 시도하세요.",
            )
        if "size" in text:
            return LlmError(
                "이 모델이 받지 않는 이미지 크기예요.",
                "크기를 정사각형(1024x1024)으로 바꿔 다시 시도하세요.",
            )
        return LlmError(
            "AI가 이미지 만들기 요청을 받아들이지 않았어요.",
            "설명 글·크기·모델 이름을 확인하세요.",
        )
    if isinstance(exc, openai.NotFoundError):
        return LlmError(
            "이 연결에서는 이미지 모델을 찾지 못했어요.",
            "단계 설정의 '이미지 모델' 이름을 확인하거나 이미지를 지원하는 연결을 고르세요.",
        )
    if isinstance(exc, openai.RateLimitError):
        quota = "quota" in code or "quota" in text or "billing" in text
        return LlmError(
            "이미지 만들기 사용 한도를 넘었어요." if quota else "이미지 요청이 너무 많아요.",
            "결제 한도를 확인해 주세요." if quota else "잠시 뒤 다시 시도하세요.",
            retryable=not quota,
        )
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LlmError(
            "이미지를 만들 권한이 없거나 AI 연결 키가 맞지 않아요.",
            "AI 연결의 키를 확인하고, 이미지 만들기가 켜진 계정인지 확인하세요.",
        )
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return LlmError(
            "AI 서버에 연결하지 못했어요.",
            "주소(base URL)와 네트워크를 확인하세요.",
            retryable=True,
        )
    return LlmError("이미지 만들기 중 문제가 생겼어요.", "잠시 뒤 다시 시도하세요.", retryable=True)


def parse_images_response(resp: Any) -> list[RawImage]:
    out: list[RawImage] = []
    for item in getattr(resp, "data", None) or []:
        b64 = getattr(item, "b64_json", None)
        url = getattr(item, "url", None)
        if b64 or url:
            out.append(
                RawImage(
                    b64=b64,
                    url=url,
                    revised_prompt=getattr(item, "revised_prompt", None),
                )
            )
    return out
