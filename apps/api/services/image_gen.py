"""이미지 만들기(v0.9): AI 연결을 고르고, 그림을 받아 검사해 워크스페이스 파일로 저장한다.

- 연결: 단계에서 고른 연결, 아니면 '기본' 연결(이미지를 못 만들면 만들 수 있는 연결 중 첫 번째).
- 그림은 base64나 주소로 오는데, 주소는 사설망 차단 규칙(safe_http)을 거쳐 받는다. 한 장 10MB, png·jpg·webp만.
- 비용은 장당 예상값(engine/pricing.IMAGE_PRICES, 참고용)으로 어림한다.
"""

import base64
import binascii
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.engine import safe_http
from api.engine.pricing import image_cost
from api.llm import registry
from api.llm.base import LlmError
from api.llm.image import MAX_COUNT, SIZES, RawImage
from api.llm.presets import default_image_model, image_capable
from api.llm.vision import sniff_mime
from api.models import LlmProvider
from api.services import files as files_svc
from api.services import run_files
from nodes import NodeError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED = ("image/png", "image/jpeg", "image/webp")
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


@dataclass
class GeneratedImages:
    files: list[dict[str, Any]]
    revised_prompt: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: Decimal


def clean_count(value: Any) -> int:
    try:
        n = int(float(str(value or 1)))
    except ValueError:
        n = 1
    return max(1, min(n, MAX_COUNT))


def clean_size(value: Any) -> str:
    size = str(value or "1024x1024").strip().lower().replace("×", "x")
    if size not in SIZES:
        raise NodeError("이미지 크기는 1024x1024, 1536x1024, 1024x1536 중에서 골라 주세요.")
    return size


def pick_connection(db: Session, workspace_id: str, ref: str) -> LlmProvider:
    rows = list(db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == workspace_id)))
    if not rows:
        raise NodeError("등록된 AI 연결이 없어요. 관리 > AI 모델에서 OpenAI 등 연결을 추가하세요.")
    if ref not in ("", "default"):
        chosen = next(
            (r for r in rows if ref in (r.id, r.label)),
            next((r for r in rows if r.provider == ref), None),
        )
        if chosen is None:
            raise NodeError(
                f"'{ref}' AI 연결을 찾지 못했어요. 단계 설정에서 AI 연결을 '기본'으로 바꾸거나 다시 고르세요."
            )
        return chosen
    default = next((r for r in rows if r.is_default), rows[0])
    if image_capable(default.provider):
        return default
    capable = next((r for r in rows if image_capable(r.provider)), None)
    if capable is None:
        raise NodeError(
            "이미지를 만들 수 있는 AI 연결(OpenAI·Azure·OpenAI 호환)이 없어요. "
            "관리 > AI 모델에서 연결을 추가하세요."
        )
    return capable


def _decode(raw: RawImage) -> bytes:
    if raw.b64:
        try:
            return base64.b64decode(raw.b64, validate=False)
        except (binascii.Error, ValueError):
            raise NodeError("AI가 돌려준 그림을 읽지 못했어요. 잠시 뒤 다시 시도하세요.") from None
    if raw.url:
        return safe_http.fetch_bytes(raw.url, max_bytes=MAX_IMAGE_BYTES)
    raise NodeError("AI가 그림을 돌려주지 않았어요. 설명 글을 바꿔 다시 시도하세요.")


def generate(
    db: Session,
    workspace_id: str,
    app_id: str | None,
    *,
    provider: str,
    model: str | None,
    prompt: str,
    size: str,
    count: int,
    user_id: str | None = None,
) -> GeneratedImages:
    if not prompt.strip():
        raise NodeError("만들 이미지를 설명하는 글을 적어 주세요. '설명' 칸이 비어 있어요.")
    row = pick_connection(db, workspace_id, provider)
    model_name = (model or "").strip() or default_image_model(row.provider)
    if not model_name:
        raise NodeError(
            f"'{row.label}' 연결로 이미지를 만들려면 이미지 모델 이름을 적어야 해요. "
            "단계 설정의 '이미지 모델' 칸에 모델(또는 배포) 이름을 적어 주세요."
        )
    try:
        resolved = registry.resolve_llm(db, workspace_id, row.id, model_name)
    except LlmError as exc:
        raise NodeError(f"{exc.message} {exc.hint}") from None
    gen = getattr(resolved.adapter, "generate_images", None)
    if gen is None:
        raise NodeError(
            f"'{row.label}' 연결은 이미지 만들기를 지원하지 않아요. "
            "OpenAI·Azure·OpenAI 호환 연결을 골라 주세요."
        )
    try:
        result = gen(model=model_name, prompt=prompt, size=size, count=count)
    except LlmError as exc:
        raise NodeError(f"{exc.message} {exc.hint}", retryable=exc.retryable) from None
    if not result.images:
        raise NodeError("AI가 그림을 돌려주지 않았어요. 설명 글을 바꿔 다시 시도하세요.")
    saved: list[dict[str, Any]] = []
    for i, raw in enumerate(result.images[:MAX_COUNT], start=1):
        data = _decode(raw)
        if len(data) > MAX_IMAGE_BYTES:
            raise NodeError(
                f"만든 그림이 너무 커요(최대 {MAX_IMAGE_BYTES // (1024 * 1024)}MB). 크기를 줄여 다시 시도하세요."
            )
        mime = sniff_mime(data)
        if mime not in ALLOWED:
            raise NodeError(
                "AI가 그림이 아닌 내용을 돌려줬어요(PNG·JPG·WEBP만 쓸 수 있어요). "
                "모델 이름과 연결을 확인하세요."
            )
        f = files_svc.save_generated(
            db,
            workspace_id,
            app_id,
            filename=f"이미지-{i}{EXT[mime]}",
            mime=mime,
            data=data,
            user_id=user_id,
        )
        saved.append(run_files.file_item(f))
    revised = next((r.revised_prompt for r in result.images if r.revised_prompt), "") or ""
    return GeneratedImages(
        files=saved,
        revised_prompt=revised,
        model=result.model or model_name,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost=image_cost(model_name, len(saved), size),
    )
