"""운영 준비 1차 B6: AI 기본법 대응(챗 'AI가 답해요' 고지, 만든 그림·파일의 AI 생성 표시)."""

import io

import pytest
from PIL import Image

from api.services import ai_label, app_config, file_export
from api.tests.fakes import tiny_png


def _img(fmt: str, size: tuple[int, int] = (64, 64)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt)
    return out.getvalue()


@pytest.mark.parametrize(
    ("mime", "data"),
    [
        ("image/png", tiny_png(32, 32)),
        ("image/jpeg", _img("JPEG")),
        ("image/webp", _img("WEBP")),
    ],
)
def test_image_metadata_label(mime: str, data: bytes) -> None:
    assert ai_label.image_label(data) is None
    out = ai_label.label_image(data, mime, model="gpt-image-1")
    assert ai_label.image_label(out) is not None
    # 그림 자체는 그대로(보이는 표시는 꺼져 있음)
    a, b = Image.open(io.BytesIO(data)).convert("RGB"), Image.open(io.BytesIO(out)).convert("RGB")
    assert a.size == b.size


def test_visible_label_changes_corner_only() -> None:
    data = _img("PNG", (400, 300))
    out = ai_label.label_image(data, "image/png", visible=True)
    img = Image.open(io.BytesIO(out)).convert("RGB")
    assert img.getpixel((5, 5)) == (200, 30, 30)  # 왼쪽 위는 그대로
    corner = [img.getpixel((x, y)) for x in range(300, 395, 5) for y in range(270, 295, 3)]
    assert any(p != (200, 30, 30) for p in corner)  # 오른쪽 아래에 글자 띠
    assert ai_label.image_label(out)


def test_broken_image_untouched() -> None:
    assert ai_label.label_image(b"not an image", "image/png") == b"not an image"


def test_docx_and_xlsx_properties() -> None:
    import docx
    from openpyxl import load_workbook

    d = file_export.build_file(
        "docx", source="text", text="# 제목\n본문", rows=None, columns=None, bom=False, sheet=""
    )
    props = docx.Document(io.BytesIO(d)).core_properties
    assert "AI 생성" in (props.comments or "") and props.author == "Genio"
    x = file_export.build_file(
        "xlsx", source="text", text="a\nb", rows=None, columns=None, bom=False, sheet="결과"
    )
    wb = load_workbook(io.BytesIO(x))
    assert "AI 생성" in (wb.properties.description or "")


def test_ai_notice_default_on_and_clean() -> None:
    f = app_config.merged_features({})
    assert f["ai_notice"]["enabled"] is True and "AI" in f["ai_notice"]["text"]
    patched = app_config.patch_features({}, {"ai_notice": {"enabled": False, "text": "  "}})
    assert patched["ai_notice"]["enabled"] is False
    assert patched["ai_notice"]["text"] == app_config.AI_NOTICE_TEXT  # 비우면 기본 문구
    long = app_config.patch_features({}, {"ai_notice": {"text": "가" * 500}})
    assert len(long["ai_notice"]["text"]) == 200


def test_image_node_has_visible_option() -> None:
    from nodes import registry

    spec = registry.get("image_generate")
    assert spec is not None and "visible_label" in spec.input_schema["properties"]
