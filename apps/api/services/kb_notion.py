"""v0.8 Notion 동기화: 내부 통합 토큰으로 페이지·데이터베이스를 읽어 마크다운으로 바꾼다.

- 연결 정보(커넥터 'notion')의 토큰을 서버에서만 꺼내 쓴다. 화면·기록·오류 문장에는 나오지 않는다.
- 페이지 id나 노션 주소를 여러 개 적을 수 있다. 데이터베이스면 그 안의 페이지를 모두 가져온다.
- 바뀐 쪽만 다시 가져온다(last_edited_time 비교). 안 바뀐 쪽은 블록을 읽지 않는다.
"""

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from api.core.crypto import decrypt_json
from api.engine import safe_http
from api.models import ConnectorCredential, ConnectorDefinition
from nodes import NodeError

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
HOSTS = ["api.notion.com"]
MAX_PAGES = 100
MAX_BLOCKS_PER_PAGE = 500
MAX_BLOCK_DEPTH = 3
CREDENTIAL_KEY = "notion"
_ID32 = re.compile(r"([0-9a-fA-F]{32})")


@dataclass
class NotionPage:
    id: str
    title: str
    url: str
    last_edited: str
    markdown: str = ""
    hash: str = ""
    unchanged: bool = False


@dataclass
class NotionResult:
    pages: list[NotionPage] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    reached_limit: bool = False


def parse_target(raw: str) -> str | None:
    """노션 주소나 id에서 32자리 id를 꺼낸다(대시 유무 무관). 없으면 None."""
    text = str(raw or "").strip().split("?")[0].replace("-", "")
    found = _ID32.findall(text)
    return found[-1].lower() if found else None


def dashed(page_id: str) -> str:
    h = page_id.replace("-", "")
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def token_of(db: Session, workspace_id: str, credential_id: str) -> str:
    cred = db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError("노션 연결 정보를 찾을 수 없어요. 연결 정보를 다시 골라 주세요.")
    d = db.get(ConnectorDefinition, cred.definition_id)
    if d is None or d.key != CREDENTIAL_KEY:
        raise NodeError("'노션' 연결 정보만 쓸 수 있어요. 연결 정보 화면에서 노션을 만들어 주세요.")
    data = decrypt_json(cred.secret_encrypted)
    token = str((data or {}).get("token") or "") if isinstance(data, dict) else ""
    if not token:
        raise NodeError("노션 연결 정보에 토큰이 비어 있어요. 내부 통합 토큰을 넣어 주세요.")
    return token


class Client:
    """노션 API 호출(안전한 HTTP, api.notion.com만). 429는 한 번 기다렸다 다시 시도한다."""

    def __init__(self, token: str, delay: float) -> None:
        self.headers = {
            "Authorization": "Bearer " + token,
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        }
        self.delay = delay
        self.calls = 0

    def call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        for attempt in (0, 1):
            if self.calls and self.delay > 0:
                time.sleep(self.delay)
            self.calls += 1
            res = safe_http.request(
                method, API + path, headers=self.headers, body=body, allowed_domains=HOSTS
            )
            status = int(res.get("status", 0))
            if status == 429 and attempt == 0:
                retry = (res.get("headers") or {}).get("retry-after")
                time.sleep(min(float(retry or 1), 5.0) if self.delay > 0 else 0)
                continue
            data = res.get("body")
            return {"status": status, "body": data if isinstance(data, dict) else {}}
        return {"status": 429, "body": {}}


def _rich(parts: Any) -> str:
    return "".join(str(p.get("plain_text", "")) for p in (parts or []) if isinstance(p, dict))


def _page_title(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _rich(prop.get("title")).strip()
    return ""


def _auth_error(status: int) -> NodeError:
    if status in (401, 403):
        return NodeError(
            "노션 인증에 실패했어요. 토큰이 맞는지, 가져올 페이지에서 '연결 추가'로 통합을 초대했는지 확인하세요."
        )
    if status == 404:
        return NodeError(
            "노션 페이지를 찾지 못했어요. 주소가 맞는지, 그 페이지에 통합을 '연결 추가'했는지 확인하세요."
        )
    if status == 429:
        return NodeError("노션이 요청이 많다고 해요. 잠시 뒤 다시 동기화하세요.", retryable=True)
    return NodeError(f"노션이 오류로 답했어요(코드 {status}). 잠시 뒤 다시 시도하세요.")


def _children(client: Client, block_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(out) < MAX_BLOCKS_PER_PAGE:
        path = f"/blocks/{block_id}/children?page_size=100" + (
            f"&start_cursor={cursor}" if cursor else ""
        )
        res = client.call("GET", path)
        if res["status"] != 200:
            raise _auth_error(int(res["status"]))
        body = res["body"]
        out.extend(b for b in (body.get("results") or []) if isinstance(b, dict))
        if not body.get("has_more") or not body.get("next_cursor"):
            break
        cursor = str(body["next_cursor"])
    return out[:MAX_BLOCKS_PER_PAGE]


def blocks_to_markdown(
    blocks: list[dict[str, Any]],
    fetch_children: Callable[[str], list[dict[str, Any]]],
    *,
    depth: int = 0,
    budget: list[int] | None = None,
    child_pages: list[str] | None = None,
) -> str:
    """노션 블록을 마크다운 글로. 하위 블록은 들여쓴다(깊이 3, 블록 500개까지)."""
    budget = budget if budget is not None else [MAX_BLOCKS_PER_PAGE]
    lines: list[str] = []
    indent = "  " * depth
    number = 0
    for b in blocks:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        kind = str(b.get("type") or "")
        data = b.get(kind) if isinstance(b.get(kind), dict) else {}
        text = _rich((data or {}).get("rich_text"))
        number = number + 1 if kind == "numbered_list_item" else 0
        line: str | None = None
        if kind == "paragraph":
            line = text
        elif kind == "heading_1":
            line = f"# {text}"
        elif kind == "heading_2":
            line = f"## {text}"
        elif kind == "heading_3":
            line = f"### {text}"
        elif kind == "bulleted_list_item":
            line = f"{indent}- {text}"
        elif kind == "numbered_list_item":
            line = f"{indent}{number}. {text}"
        elif kind == "to_do":
            line = f"{indent}- [{'x' if (data or {}).get('checked') else ' '}] {text}"
        elif kind == "quote" or kind == "callout":
            line = f"> {text}"
        elif kind == "toggle":
            line = f"{indent}- {text}"
        elif kind == "code":
            lang = str((data or {}).get("language") or "")
            line = f"```{lang}\n{text}\n```"
        elif kind == "divider":
            line = "---"
        elif kind in ("bookmark", "embed", "link_preview"):
            line = str((data or {}).get("url") or "")
        elif kind in ("image", "file", "pdf", "video"):
            cap = _rich((data or {}).get("caption"))
            line = f"[{kind}] {cap}".strip() if cap else None
        elif kind == "child_page":
            title = str((data or {}).get("title") or "")
            line = f"- (하위 페이지) {title}"
            if child_pages is not None and b.get("id"):
                child_pages.append(str(b["id"]))
        elif kind == "table":
            rows = fetch_children(str(b["id"])) if b.get("id") else []
            table_lines = []
            for r in rows:
                cells = (r.get("table_row") or {}).get("cells") or []
                table_lines.append("| " + " | ".join(_rich(c) for c in cells) + " |")
            line = "\n".join(table_lines)
        if line:
            lines.append(line)
        if (
            b.get("has_children")
            and kind not in ("table", "child_page", "child_database")
            and depth < MAX_BLOCK_DEPTH
            and b.get("id")
        ):
            sub = blocks_to_markdown(
                fetch_children(str(b["id"])),
                fetch_children,
                depth=depth + 1,
                budget=budget,
                child_pages=child_pages,
            )
            if sub:
                lines.append(sub)
    return "\n\n".join(x for x in lines if x is not None)


def _load_page(
    client: Client,
    page: dict[str, Any],
    known: dict[str, str],
    child_pages: list[str] | None,
) -> NotionPage:
    pid = str(page.get("id") or "").replace("-", "")
    edited = str(page.get("last_edited_time") or "")
    title = _page_title(page) or "제목 없는 노션 페이지"
    out = NotionPage(id=pid, title=title, url=str(page.get("url") or ""), last_edited=edited)
    if edited and known.get(pid) == edited and child_pages is None:
        out.unchanged = True
        return out
    md = blocks_to_markdown(
        _children(client, pid), lambda bid: _children(client, bid), child_pages=child_pages
    )
    out.markdown = f"# {title}\n\n{md}".strip()
    out.hash = hashlib.sha256(out.markdown.encode("utf-8")).hexdigest()
    return out


def fetch(
    token: str,
    targets: list[str],
    *,
    known: dict[str, str],
    include_children: bool = False,
    delay: float = 0.34,
    on_progress: Callable[[int, int], None] | None = None,
    max_pages: int = MAX_PAGES,
) -> NotionResult:
    """targets(페이지·데이터베이스 id)의 쪽을 가져온다. known = {페이지 id: 지난번 last_edited_time}."""
    client = Client(token, delay)
    result = NotionResult()
    seen: set[str] = set()

    def add(page_obj: dict[str, Any], depth: int) -> None:
        pid = str(page_obj.get("id") or "").replace("-", "")
        if not pid or pid in seen:
            return
        if len(result.pages) >= max_pages:
            result.reached_limit = True
            return
        seen.add(pid)
        kids: list[str] | None = [] if include_children and depth < 2 else None
        try:
            page = _load_page(client, page_obj, known, kids)
        except NodeError as exc:
            result.failed.append((pid, exc.message))
            return
        result.pages.append(page)
        if on_progress:
            on_progress(len(result.pages), max_pages)
        for child_id in kids or []:
            cid = child_id.replace("-", "")
            if cid in seen:
                continue
            res = client.call("GET", f"/pages/{cid}")
            if res["status"] == 200:
                add(res["body"], depth + 1)

    for raw in targets:
        tid = parse_target(raw)
        if tid is None:
            result.failed.append((str(raw)[:80], "노션 페이지 주소나 id 형식이 아니에요."))
            continue
        res = client.call("GET", f"/pages/{tid}")
        if res["status"] == 200:
            add(res["body"], 0)
            continue
        if res["status"] != 404:
            result.failed.append((tid, _auth_error(int(res["status"])).message))
            continue
        db_res = client.call("GET", f"/databases/{tid}")
        if db_res["status"] != 200:
            result.failed.append((tid, _auth_error(int(db_res["status"])).message))
            continue
        cursor: str | None = None
        while len(result.pages) < max_pages:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            q = client.call("POST", f"/databases/{tid}/query", body)
            if q["status"] != 200:
                result.failed.append((tid, _auth_error(int(q["status"])).message))
                break
            for item in q["body"].get("results") or []:
                if isinstance(item, dict):
                    add(item, 0)
            if not q["body"].get("has_more") or not q["body"].get("next_cursor"):
                break
            cursor = str(q["body"]["next_cursor"])
    return result
