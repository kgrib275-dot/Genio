"""AI가 만든 결과물에 'AI 생성' 표시 남기기(운영 준비 1차 B6, AI 기본법 생성형 AI 결과물 표시).

- 그림(이미지 만들기 단계): 파일 정보(PNG 글 칸, JPG·WEBP EXIF)에 늘 남긴다(보이지 않는 표시).
  단계에서 '그림에 AI 생성 표시'를 켜면 오른쪽 아래에 보이는 글자도 넣는다.
- 워드·엑셀(파일 만들기 단계): 문서 속성(만든 프로그램·설명·키워드)에 남긴다.
법률 검토를 대신하지 않는다. 표시 방식은 시행령·가이드에 맞춰 바꿀 수 있게 한곳에 모았다.
"""

import io
from typing import Any

GENERATOR = "Genio"
DESCRIPTION = "AI 생성 콘텐츠(Genio)"
DESCRIPTION_EN = "AI-generated content (Genio)"
KEYWORDS = "AI 생성, AI-generated"
VISIBLE_TEXT = "AI-generated"

# EXIF 태그 번호: ImageDescription, Software
_EXIF_DESCRIPTION = 0x010E
_EXIF_SOFTWARE = 0x0131


def label_image(data: bytes, mime: str, *, model: str = "", visible: bool = False) -> bytes:
    """그림에 AI 생성 표시를 넣은 새 바이트. 읽지 못하는 그림이면 그대로 돌려준다."""
    from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

    try:
        img: Any = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return data
    if visible:
        img = img.convert("RGBA")
        w, h = img.size
        size = max(12, min(w, h) // 28)
        try:
            font: Any = ImageFont.load_default(size=size)
        except TypeError:  # 아주 옛 Pillow
            font = ImageFont.load_default()
        draw = ImageDraw.Draw(img)
        box = draw.textbbox((0, 0), VISIBLE_TEXT, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        pad = max(4, size // 3)
        x, y = w - tw - pad * 3, h - th - pad * 3
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.rectangle((x - pad, y - pad, x + tw + pad, y + th + pad * 2), fill=(0, 0, 0, 140))
        od.text((x, y), VISIBLE_TEXT, font=font, fill=(255, 255, 255, 230))
        img = Image.alpha_composite(img, overlay)
    out = io.BytesIO()
    if mime == "image/png":
        info = PngImagePlugin.PngInfo()
        info.add_text("AI-Generated", "true")
        info.add_text("Software", GENERATOR)
        info.add_text("Description", DESCRIPTION_EN)
        if model:
            info.add_text("AI-Model", model[:100])
        img.save(out, format="PNG", pnginfo=info)
    else:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        exif = img.getexif()
        exif[_EXIF_DESCRIPTION] = DESCRIPTION_EN + (f" / {model[:100]}" if model else "")
        exif[_EXIF_SOFTWARE] = GENERATOR
        fmt = "WEBP" if mime == "image/webp" else "JPEG"
        img.save(out, format=fmt, exif=exif, quality=95)
    return out.getvalue()


def image_label(data: bytes) -> str | None:
    """그림에 남긴 AI 생성 표시(시험·확인용). 없으면 None."""
    from PIL import Image

    try:
        img: Any = Image.open(io.BytesIO(data))
    except Exception:
        return None
    text = getattr(img, "text", None) or {}
    if text.get("AI-Generated") == "true":
        return str(text.get("Description") or "")
    desc = img.getexif().get(_EXIF_DESCRIPTION)
    return str(desc) if desc and "AI-generated" in str(desc) else None


def label_docx_document(doc: Any) -> None:
    props = doc.core_properties
    props.author = GENERATOR
    props.comments = DESCRIPTION
    props.keywords = KEYWORDS


def label_workbook(wb: Any) -> None:
    props = wb.properties
    props.creator = GENERATOR
    props.description = DESCRIPTION
    props.keywords = KEYWORDS
