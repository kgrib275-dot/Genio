"""이미지 입력(비전, v0.6): 공급자별 요청 형식으로 바꾼다.

AI 단계의 `images`에는 올린 파일 id(입력 단계의 파일 항목) 또는 공개 https 이미지 주소가 온다.
엔진(RunServices)이 파일·주소를 읽어 ImageInput(형식·바이트)으로 만들고, 어댑터는 이 모듈로
OpenAI·Anthropic·Google 각자의 형식에 담는다. 주소도 서버가 직접 받아 base64로 보낸다
(공급자마다 주소 지원이 달라서 한 방식으로 맞추고, 사설망 차단 규칙을 그대로 적용하기 위해).
"""

import base64
from dataclasses import dataclass
from typing import Any

ALLOWED_MIME = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 4


@dataclass(frozen=True)
class ImageInput:
    mime: str
    data: bytes
    name: str = ""

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def data_url(self) -> str:
        return f"data:{self.mime};base64,{self.b64()}"


def sniff_mime(data: bytes) -> str | None:
    """앞부분 바이트로 이미지 형식을 알아낸다(올린 사람이 붙인 형식은 믿지 않는다)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageError(ValueError):
    """두 줄 오류: (무엇이 문제인지, 어떻게 하면 되는지)."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(f"{message} {hint}")
        self.message = message
        self.hint = hint


def check_image(data: bytes, name: str = "") -> ImageInput:
    label = f"'{name}'" if name else "이미지"
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            f"{label} 파일이 너무 커요(최대 5MB).", "더 작은 이미지로 줄여서 다시 올려 주세요."
        )
    mime = sniff_mime(data)
    if mime is None:
        raise ImageError(
            f"{label}은(는) AI가 읽을 수 있는 이미지가 아니에요.",
            "PNG·JPG·GIF·WEBP 이미지만 넣을 수 있어요.",
        )
    return ImageInput(mime=mime, data=data, name=name)


# ---- 공급자별 형식 ----
def openai_user_content(prompt: str, images: list[ImageInput]) -> str | list[dict[str, Any]]:
    if not images:
        return prompt
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    parts += [{"type": "image_url", "image_url": {"url": img.data_url()}} for img in images]
    return parts


def anthropic_user_content(prompt: str, images: list[ImageInput]) -> str | list[dict[str, Any]]:
    if not images:
        return prompt
    parts: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": img.mime, "data": img.b64()},
        }
        for img in images
    ]
    parts.append({"type": "text", "text": prompt})
    return parts


def google_parts(prompt: str, images: list[ImageInput]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [
        {"inline_data": {"mime_type": img.mime, "data": img.b64()}} for img in images
    ]
    parts.append({"text": prompt})
    return parts
