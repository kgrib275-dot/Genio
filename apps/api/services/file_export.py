"""파일 만들기(v0.9): 글·표를 txt·md·csv·json·xlsx·docx 파일로 만든다(순수 함수, DB·저장소는 모른다).

- 표(xlsx·csv)는 목록(딕셔너리 목록·값 목록)에서 만든다. 열은 자동 또는 지정.
- 엑셀·CSV에서 수식으로 실행되지 않게 =, +, -, @로 시작하는 글을 막는다(csv는 앞에 작은따옴표, xlsx는 글 형식으로 저장).
- 10MB·5만 줄을 넘으면 두 줄 오류로 멈춘다. pdf는 쓸 수 있는 라이브러리가 없어 지원하지 않는다.
"""

import csv
import io
import json
import re
from typing import Any

from nodes import NodeError

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 50
MAX_CELL_CHARS = 32_000  # 엑셀 한 칸 한도(32,767자)보다 조금 작게

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FORMATS: dict[str, tuple[str, str]] = {
    "txt": ("text/plain; charset=utf-8", ".txt"),
    "md": ("text/markdown; charset=utf-8", ".md"),
    "csv": ("text/csv; charset=utf-8", ".csv"),
    "json": ("application/json", ".json"),
    "xlsx": (XLSX_MIME, ".xlsx"),
    "docx": (DOCX_MIME, ".docx"),
}
FORMAT_LABELS = {
    "txt": "글 파일(.txt)",
    "md": "마크다운(.md)",
    "csv": "CSV(.csv)",
    "json": "JSON(.json)",
    "xlsx": "엑셀(.xlsx)",
    "docx": "워드(.docx)",
}
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_DANGEROUS_START = ("=", "+", "-", "@", "\t", "\r")


def safe_filename(name: str, fmt: str) -> str:
    """경로 문자·제어 문자를 지우고 100자 안으로 줄여 확장자를 붙인다."""
    ext = FORMATS[fmt][1]
    base = _BAD_NAME.sub(" ", str(name or "")).strip(" .")
    base = re.sub(r"\s+", " ", base)
    if base.lower().endswith(ext):
        base = base[: -len(ext)].rstrip(". ")
    base = base[:100].strip(" .") or "파일"
    return base + ext


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "예" if v else "아니요"
    if isinstance(v, (int, float, str)):
        s = str(v)
    else:
        s = json.dumps(v, ensure_ascii=False, default=str)
    return s[:MAX_CELL_CHARS]


def table_from(rows: Any, columns: list[str] | None = None) -> tuple[list[str], list[list[str]]]:
    """목록 값을 (머리글, 줄들)로. 딕셔너리 목록·값 목록·글(JSON 또는 줄 목록)을 받는다."""
    if isinstance(rows, str):
        text = rows.strip()
        try:
            rows = json.loads(text) if text[:1] in "[{" else text.splitlines()
        except ValueError:
            rows = text.splitlines()
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        raise NodeError("표로 만들 목록이 비어 있어요. '목록' 칸에 앞 단계의 목록 값을 끌어오세요.")
    if len(rows) > MAX_ROWS:
        raise NodeError(
            f"줄이 너무 많아요(최대 {MAX_ROWS:,}줄, 지금 {len(rows):,}줄). 목록을 줄여서 다시 해 주세요."
        )
    if all(isinstance(r, dict) for r in rows):
        if columns:
            headers = columns
        else:
            headers = []
            for r in rows:
                for k in r:
                    if str(k) not in headers:
                        headers.append(str(k))
                if len(headers) > MAX_COLUMNS:
                    break
            headers = headers[:MAX_COLUMNS]
        body = [[_cell(r.get(h)) for h in headers] for r in rows]
        return headers, body
    if all(isinstance(r, (list, tuple)) for r in rows):
        width = min(max(len(r) for r in rows), MAX_COLUMNS)
        headers = columns or [f"열{i + 1}" for i in range(width)]
        return headers, [[_cell(c) for c in list(r)[: len(headers)]] for r in rows]
    return columns[:1] if columns else ["값"], [[_cell(r)] for r in rows]


def _csv_safe(v: str) -> str:
    return "'" + v if v[:1] in _DANGEROUS_START else v


def build_csv(headers: list[str], body: list[list[str]], *, bom: bool) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([_csv_safe(h) for h in headers])
    for r in body:
        w.writerow([_csv_safe(c) for c in r])
    data = buf.getvalue().encode("utf-8")
    return b"\xef\xbb\xbf" + data if bom else data


def build_xlsx(headers: list[str], body: list[list[str]], sheet: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    if ws is None:  # pragma: no cover - 새 통합 문서에는 항상 시트가 있다
        raise NodeError("엑셀 파일을 만들지 못했어요. 잠시 뒤 다시 시도하세요.")
    ws.title = (re.sub(r"[\\/*?:\[\]]", " ", sheet or "결과").strip() or "결과")[:31]
    bold = Font(bold=True)

    def put(row: int, col: int, text: str, *, head: bool = False) -> None:
        c = ws.cell(row=row, column=col, value=text)
        c.data_type = "s"  # 수식이 아니라 글로 저장(=로 시작해도 실행되지 않는다)
        if head:
            c.font = bold

    for ci, h in enumerate(headers, start=1):
        put(1, ci, h, head=True)
    for ri, r in enumerate(body, start=2):
        for ci, v in enumerate(r, start=1):
            put(ri, ci, v)
    for ci, h in enumerate(headers, start=1):
        widest = max([len(h), *[len(r[ci - 1]) for r in body[:200] if ci - 1 < len(r)]])
        ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = min(
            max(widest + 2, 8), 60
        )
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


_BOLD = re.compile(r"(\*\*[^*]+\*\*)")


def _add_runs(paragraph: Any, text: str) -> None:
    for part in _BOLD.split(text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part:
            paragraph.add_run(part)


def build_docx(text: str | None, table: tuple[list[str], list[list[str]]] | None) -> bytes:
    """글은 간단한 마크다운(#·##·###·-·1.·**굵게**)을, 표는 머리글이 굵은 표를 워드 문서로."""
    import docx

    d = docx.Document()
    if table is not None:
        headers, body = table
        t = d.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        for i, h in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = ""
            cell.paragraphs[0].add_run(h).bold = True
        for r in body:
            cells = t.add_row().cells
            for i, v in enumerate(r[: len(headers)]):
                cells[i].text = v
    else:
        buf: list[str] = []

        def flush() -> None:
            if buf:
                _add_runs(d.add_paragraph(), " ".join(buf))
                buf.clear()

        for raw in (text or "").splitlines():
            line = raw.rstrip()
            m = re.match(r"^(#{1,3})\s+(.*)$", line)
            if m:
                flush()
                d.add_heading(m.group(2).strip(), level=len(m.group(1)))
            elif re.match(r"^\s*[-*]\s+", line):
                flush()
                _add_runs(d.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*]\s+", "", line))
            elif re.match(r"^\s*\d+[.)]\s+", line):
                flush()
                _add_runs(d.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", line))
            elif not line.strip():
                flush()
            else:
                buf.append(line.strip())
        flush()
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def build_file(
    fmt: str,
    *,
    source: str,
    text: str,
    rows: Any,
    columns: list[str] | None,
    bom: bool,
    sheet: str,
) -> bytes:
    """형식에 맞는 파일 내용(바이트). 크기 한도를 넘으면 NodeError."""
    if fmt not in FORMATS:
        raise NodeError("파일 형식을 '글·마크다운·CSV·JSON·엑셀·워드' 중에서 골라 주세요.")
    table: tuple[list[str], list[list[str]]] | None = None
    if source == "table":
        table = table_from(rows, columns)
    data: bytes
    if fmt in ("txt", "md"):
        if table is not None:
            h, b = table
            text = "\n".join("\t".join(r) for r in [h, *b])
        data = text.encode("utf-8")
    elif fmt == "json":
        if table is not None:
            h, b = table
            payload: Any = [dict(zip(h, r, strict=False)) for r in b]
        else:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {"text": text}
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    elif fmt in ("csv", "xlsx"):
        if table is None:
            lines = [ln for ln in text.splitlines() if ln.strip()] or [text]
            if len(lines) > MAX_ROWS:
                raise NodeError(
                    f"줄이 너무 많아요(최대 {MAX_ROWS:,}줄). 글을 줄여서 다시 해 주세요."
                )
            table = (["내용"], [[ln[:MAX_CELL_CHARS]] for ln in lines])
        data = build_csv(*table, bom=bom) if fmt == "csv" else build_xlsx(table[0], table[1], sheet)
    else:  # docx
        data = build_docx(None if table is not None else text, table)
    if len(data) > MAX_FILE_BYTES:
        raise NodeError(
            f"파일이 너무 커요(최대 {MAX_FILE_BYTES // (1024 * 1024)}MB). 내용을 줄여서 다시 해 주세요."
        )
    return data
