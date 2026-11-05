"""v0.9 이미지 만들기(image_generate)와 파일 만들기(file_export).

두 단계 모두 만든 파일을 워크스페이스 파일로 저장하고, 출력에 {id, filename, mime, size}를 담는다.
챗·입력 폼·실행 기록·일괄 실행 결과가 이 출력을 보고 내려받기 링크를 만든다.
"""

from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}
IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536"]
FILE_FORMATS = ["txt", "md", "csv", "json", "xlsx", "docx"]


# ---------------- 이미지 만들기 ----------------
def _run_image_generate(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    prompt = ctx.render(str(data.get("prompt") or "")).strip()
    style = ctx.render(str(data.get("style") or "")).strip()
    if not prompt:
        raise NodeError("만들 이미지를 설명하는 글을 적어 주세요. '이미지 설명' 칸이 비어 있어요.")
    full = f"{prompt}\n\n[스타일·피할 것] {style}" if style else prompt
    size = str(data.get("size") or "1024x1024")
    if size not in IMAGE_SIZES:
        raise NodeError("이미지 크기는 1024x1024, 1536x1024, 1024x1536 중에서 골라 주세요.")
    try:
        count = max(1, min(int(float(str(data.get("count") or 1))), 4))
    except ValueError:
        count = 1
    res = ctx.services.generate_images(
        provider=str(data.get("provider") or "default"),
        model=str(data.get("model") or "").strip() or None,
        prompt=full,
        size=size,
        count=count,
    )
    files = res.get("files") or []
    ctx.log(f"이미지 {len(files)}장을 만들었어요(예상 비용 약 ${res.get('cost', 0):.3f}, 참고용).")
    return NodeResult(
        output={
            "files": files,
            "first_file_id": files[0]["id"] if files else "",
            "count": len(files),
            "revised_prompt": str(res.get("revised_prompt") or ""),
        }
    )


IMAGE_GENERATE = NodeSpec(
    type="image_generate",
    label="이미지 만들기",
    category="AI",
    description=(
        "AI로 그림을 만들어요. 설명 글을 넣으면 이미지 파일이 만들어지고, 챗 답이나 실행 기록에서 "
        "바로 보고 내려받을 수 있어요. OpenAI·Azure·OpenAI 호환 연결이 필요해요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "prompt": {"type": "string", "title": "이미지 설명"},
            "style": {"type": "string", "title": "스타일·피할 것(선택)"},
            "size": {
                "type": "string",
                "title": "크기",
                "enum": IMAGE_SIZES,
                "default": "1024x1024",
            },
            "count": {
                "type": "integer",
                "title": "장 수(1~4)",
                "minimum": 1,
                "maximum": 4,
                "default": 1,
            },
            "provider": {"type": "string", "title": "AI 연결", "default": "default"},
            "model": {"type": "string", "title": "이미지 모델(비우면 연결의 대표 모델)"},
        },
        "required": ["prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "files": {"type": "array"},
            "first_file_id": {"type": "string"},
            "count": {"type": "integer"},
            "revised_prompt": {"type": "string"},
        },
    },
    ui_schema={"prompt": {"ui:widget": "textarea"}, "style": {"ui:widget": "textarea"}},
    run=_run_image_generate,
    outputs=lambda d: ["files", "first_file_id", "count", "revised_prompt"],
)


# ---------------- 파일 만들기 ----------------
def _columns(raw: Any, ctx: NodeContext) -> list[str] | None:
    value = ctx.render(raw) if isinstance(raw, str) else raw
    if isinstance(value, list):
        names = [str(c).strip() for c in value if str(c).strip()]
    else:
        names = [c.strip() for c in str(value or "").replace("\n", ",").split(",") if c.strip()]
    return names[:50] or None


def _run_file_export(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    fmt = str(data.get("format") or "txt")
    if fmt not in FILE_FORMATS:
        raise NodeError("파일 형식을 '글·마크다운·CSV·JSON·엑셀·워드' 중에서 골라 주세요.")
    source = str(data.get("source") or ("table" if fmt in ("csv", "xlsx") else "text"))
    if source not in ("text", "table"):
        source = "text"
    filename = ctx.render(str(data.get("filename") or "")).strip() or "결과"
    text = ctx.render(str(data.get("text") or ""))
    rows = ctx.render_value(data.get("rows")) if source == "table" else None
    if source == "text" and not text.strip():
        raise NodeError("파일에 넣을 내용을 적어 주세요. '내용' 칸이 비어 있어요.")
    res = ctx.services.export_file(
        fmt=fmt,
        filename=filename,
        source=source,
        text=text,
        rows=rows,
        columns=_columns(data.get("columns"), ctx),
        bom=bool(data.get("bom", True)),
        sheet=ctx.render(str(data.get("sheet") or "")).strip() or "결과",
    )
    ctx.log(f"'{res['file']['filename']}' 파일을 만들었어요({res['file']['size']:,}바이트).")
    return NodeResult(
        output={
            "file": res["file"],
            "file_id": res["file"]["id"],
            "filename": res["file"]["filename"],
        }
    )


FILE_EXPORT = NodeSpec(
    type="file_export",
    label="파일 만들기",
    category="데이터",
    description=(
        "글이나 표(목록)를 파일로 만들어요. 엑셀·워드·CSV·마크다운·JSON·글 파일을 만들 수 있고, "
        "챗 답이나 실행 기록에서 바로 내려받을 수 있어요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "format": {
                "type": "string",
                "title": "파일 형식",
                "enum": FILE_FORMATS,
                "default": "xlsx",
            },
            "filename": {
                "type": "string",
                "title": "파일 이름(확장자는 알아서)",
                "default": "결과",
            },
            "source": {
                "type": "string",
                "title": "무엇으로 만들까요",
                "enum": ["text", "table"],
                "default": "text",
            },
            "text": {"type": "string", "title": "내용(글 — 값 끌어오기 가능)"},
            "rows": {"type": "string", "title": "목록(표로 만들 때 — 앞 단계의 목록 값)"},
            "columns": {"type": "string", "title": "열 이름(쉼표로 구분, 비우면 자동)"},
            "sheet": {"type": "string", "title": "시트 이름(엑셀)", "default": "결과"},
            "bom": {
                "type": "boolean",
                "title": "엑셀에서 한글이 깨지지 않게 하기(CSV)",
                "default": True,
            },
        },
        "required": ["format"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "file": {"type": "object"},
            "file_id": {"type": "string"},
            "filename": {"type": "string"},
        },
    },
    ui_schema={"text": {"ui:widget": "textarea"}},
    run=_run_file_export,
    outputs=lambda d: ["file", "file_id", "filename"],
)

FILE_SPECS = [IMAGE_GENERATE, FILE_EXPORT]


def register_files(reg: NodeRegistry) -> None:
    for spec in FILE_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
