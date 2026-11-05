"""v0.8 공개 Google 문서 가져오기: '링크가 있는 모든 사용자'가 볼 수 있는 문서·시트·슬라이드·드라이브 파일.

비공개 파일(로그인이 필요한 파일)은 가져올 수 없다. 개인 드라이브 연결(OAuth)은 이번 범위 밖이다(ADR 0012).
- 문서 → 글(txt), 시트 → 글(줄마다 '머리글: 값'), 슬라이드 → 글(txt), 드라이브 파일(PDF·텍스트) → 그대로.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from api.engine import safe_http
from nodes import NodeError

HOSTS = ["google.com", "googleusercontent.com"]
MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 400_000
MAX_SHEET_ROWS = 5000
_ID = r"([A-Za-z0-9_-]{15,})"
PRIVATE_HINT = "Google 문서의 '공유'에서 '링크가 있는 모든 사용자'로 바꾼 뒤 다시 가져오세요."


@dataclass
class GoogleDoc:
    key: str  # 같은 문서를 다시 가져올 때 알아보는 값(종류+id[+시트 번호])
    kind: str  # doc | sheet | slides | file
    title: str
    filename: str
    mime: str
    content: bytes
    hash: str
    url: str


def parse_link(url: str) -> tuple[str, str, str | None]:
    """(종류, id, 시트 gid). 알아볼 수 없으면 NodeError."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    path = p.path
    gid = None
    for part in (p.query, p.fragment):
        m = re.search(r"(?:^|[&?])gid=(\d+)", part or "")
        if m:
            gid = m.group(1)
    if host == "docs.google.com":
        for kind, name in (
            ("doc", "document"),
            ("sheet", "spreadsheets"),
            ("slides", "presentation"),
        ):
            m = re.search(rf"/{name}/d/{_ID}", path)
            if m:
                return kind, m.group(1), gid
    if host == "drive.google.com":
        m = re.search(rf"/file/d/{_ID}", path) or None
        if m:
            return "file", m.group(1), None
        q = parse_qs(p.query).get("id")
        if q and re.fullmatch(r"[A-Za-z0-9_-]{15,}", q[0]):
            return "file", q[0], None
    raise NodeError(
        "Google 문서·시트·슬라이드·드라이브 파일 주소가 아니에요. 공유 링크를 그대로 붙여 넣어 주세요."
    )


def export_url(kind: str, doc_id: str, gid: str | None) -> str:
    if kind == "doc":
        return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    if kind == "sheet":
        extra = f"&gid={gid}" if gid else ""
        return f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv{extra}"
    if kind == "slides":
        return f"https://docs.google.com/presentation/d/{doc_id}/export?format=txt"
    return f"https://drive.google.com/uc?export=download&id={doc_id}"


def _title_from(headers: dict[str, str], fallback: str) -> str:
    cd = headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
    name = unquote(m.group(1)) if m else ""
    if not name:
        m = re.search(r'filename="?([^";]+)"?', cd, re.I)
        name = m.group(1) if m else ""
    name = re.sub(r"\.(txt|csv|pdf|md)$", "", name.strip(), flags=re.I)
    return name or fallback


def _private() -> NodeError:
    return NodeError(f"이 파일은 공개되어 있지 않아요. {PRIVATE_HINT}")


def sheet_to_text(raw: str) -> str:
    rows = list(csv.reader(io.StringIO(raw)))[: MAX_SHEET_ROWS + 1]
    if not rows:
        return ""
    head = [h.strip() or f"열{i + 1}" for i, h in enumerate(rows[0])]
    lines = []
    for r in rows[1:]:
        cells = [f"{head[i]}: {v.strip()}" for i, v in enumerate(r) if i < len(head) and v.strip()]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def fetch(url: str, *, name: str = "") -> GoogleDoc:
    kind, doc_id, gid = parse_link(url)
    target = export_url(kind, doc_id, gid)
    res = safe_http.fetch_raw(
        target,
        max_bytes=MAX_BYTES,
        allowed_domains=HOSTS,
        headers={"User-Agent": "GenioBot/0.8"},
    )
    status = int(res["status"])
    body: bytes = res["body"]
    headers: dict[str, str] = {k.lower(): v for k, v in (res.get("headers") or {}).items()}
    ctype = headers.get("content-type", "").lower()
    if status in (401, 403, 404):
        raise _private()
    if status >= 400:
        raise NodeError(f"Google이 오류로 답했어요(코드 {status}). 잠시 뒤 다시 시도하세요.")
    # 비공개 파일은 로그인 화면(HTML)으로 넘어간다
    if "html" in ctype:
        raise _private()
    key = f"{kind}:{doc_id}" + (f":{gid}" if gid else "")
    label = {"doc": "문서", "sheet": "시트", "slides": "슬라이드", "file": "파일"}[kind]
    title = name.strip() or _title_from(headers, f"Google {label} {doc_id[:6]}")
    if kind == "file":
        if body.startswith(b"%PDF"):
            return GoogleDoc(
                key, kind, title, f"{title}.pdf", "application/pdf", body,
                hashlib.sha256(body).hexdigest(), url,
            )  # fmt: skip
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NodeError(
                "드라이브 파일은 PDF나 텍스트 파일만 가져올 수 있어요. 문서·시트·슬라이드는 그 앱 링크를 쓰세요."
            ) from exc
    else:
        text = body.decode("utf-8", errors="replace")
        if kind == "sheet":
            text = sheet_to_text(text)
    text = text.lstrip("﻿").strip()[:MAX_TEXT_CHARS]
    if len(text) < 5:
        raise NodeError("가져온 문서에 글이 거의 없어요. 내용이 있는 문서인지 확인하세요.")
    content = f"# {title}\n\n{text}".encode()
    return GoogleDoc(
        key,
        kind,
        title,
        f"{title}.md",
        "text/markdown",
        content,
        hashlib.sha256(content).hexdigest(),
        url,
    )


def describe(doc: GoogleDoc) -> dict[str, Any]:
    return {"title": doc.title, "kind": doc.kind, "size": len(doc.content)}
