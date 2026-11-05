"""v0.8 웹사이트 여러 쪽 가져오기(크롤러).

시작 주소에서 같은 사이트의 쪽을 따라가며 글을 모은다.
- 깊이 2단계, 최대 50쪽, 허용·제외 주소 패턴, robots.txt 따르기, 같은 쪽(정규 주소) 한 번만.
- 모든 요청은 safe_http(사설 IP·localhost 차단, 크기·시간 제한, 리다이렉트 재검사)를 거친다.
- 쪽과 쪽 사이에 잠깐 쉰다(robots의 Crawl-delay가 있으면 따른다, 최대 5초).
"""

import fnmatch
import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from api.engine import safe_http
from nodes import NodeError

USER_AGENT = "GenioBot/0.8 (지식베이스 가져오기)"
MAX_DEPTH = 2
MAX_PAGES = 50
MAX_TEXT_CHARS = 200_000
MIN_TEXT_CHARS = 20
MAX_CRAWL_DELAY = 5.0
SKIP_EXT = (
    ".pdf",
    ".zip",
    ".gz",
    ".rar",
    ".7z",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".exe",
    ".dmg",
)
_TRACKING = re.compile(r"^(utm_.+|fbclid|gclid|yclid|mc_cid|mc_eid|ref|ref_src)$", re.I)
_HREF = re.compile(r"""(?is)<a\s[^>]*?href\s*=\s*["']([^"'#][^"']*)["']""")
_CANON = re.compile(
    r"""(?is)<link\s[^>]*?rel\s*=\s*["']canonical["'][^>]*?href\s*=\s*["']([^"']+)["']"""
)


@dataclass
class Page:
    url: str  # 정규 주소
    title: str
    text: str
    hash: str


@dataclass
class CrawlResult:
    pages: list[Page] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_robots: int = 0
    skipped_other: int = 0
    reached_limit: bool = False


def host_key(host: str) -> str:
    h = (host or "").lower()
    return h[4:] if h.startswith("www.") else h


def canonical(url: str, base: str | None = None) -> str:
    """같은 쪽을 한 주소로: 조각(#…)·추적용 값·꼬리 슬래시·기본 포트를 정리한다."""
    full = urljoin(base, url) if base else url
    p = urlsplit(full.strip())
    scheme = (p.scheme or "http").lower()
    netloc = (p.hostname or "").lower()
    if p.port and not (
        (scheme == "http" and p.port == 80) or (scheme == "https" and p.port == 443)
    ):
        netloc = f"{netloc}:{p.port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)))
    return urlunsplit((scheme, netloc, path, query, ""))


def _pattern_match(pattern: str, url: str) -> bool:
    p = urlsplit(url)
    target = (p.path or "/") + (f"?{p.query}" if p.query else "")
    pat = pattern.strip()
    if not pat:
        return False
    if "*" in pat or "?" in pat:
        return fnmatch.fnmatch(target.lower(), pat.lower())
    return pat.lower() in target.lower()


def allowed(url: str, include: list[str], exclude: list[str]) -> bool:
    if any(_pattern_match(x, url) for x in exclude):
        return False
    return not include or any(_pattern_match(x, url) for x in include)


def extract_links(html: str, base: str) -> list[str]:
    out: list[str] = []
    for m in _HREF.finditer(html):
        href = m.group(1).strip()
        low = href.lower()
        if low.startswith(("mailto:", "tel:", "javascript:", "data:", "sms:")):
            continue
        try:
            out.append(canonical(href, base))
        except ValueError:
            continue
    return out


def _fetch_robots(origin: str, fetch: Callable[..., dict[str, Any]]) -> RobotFileParser | None:
    try:
        res = fetch("GET", origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
    except NodeError:
        return None
    body = res.get("body")
    if int(res.get("status", 0)) != 200 or not isinstance(body, str):
        return None
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp


def validate_start(url: str) -> str:
    """시작 주소를 정리하고 막힌 주소면 NodeError."""
    clean = canonical(url)
    safe_http.check_url(clean)
    return clean


def page_text(html: str) -> tuple[str, str]:
    from api.services.knowledge import html_to_text

    title, text = html_to_text(html)
    return title, text[:MAX_TEXT_CHARS]


def crawl(
    start_url: str,
    *,
    depth: int = 1,
    max_pages: int = 20,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    delay: float = 0.3,
    on_progress: Callable[[int, int], None] | None = None,
    fetch: Callable[..., dict[str, Any]] | None = None,
) -> CrawlResult:
    """시작 주소부터 같은 사이트 쪽을 모은다. depth·max_pages는 한도 안으로 줄여 쓴다."""
    fetch = fetch or safe_http.request
    depth = max(0, min(int(depth), MAX_DEPTH))
    max_pages = max(1, min(int(max_pages), MAX_PAGES))
    inc = [x for x in (include or []) if x.strip()][:20]
    skip = [x for x in (exclude or []) if x.strip()][:20]
    start = canonical(start_url)
    start_host = host_key(urlsplit(start).hostname or "")
    parts = urlsplit(start)
    robots = _fetch_robots(f"{parts.scheme}://{parts.netloc}", fetch)
    crawl_delay = 0.0
    if robots is not None:
        raw = robots.crawl_delay(USER_AGENT)
        if raw:
            crawl_delay = min(float(raw), MAX_CRAWL_DELAY)
    wait = max(float(delay), crawl_delay)

    result = CrawlResult()
    queue: list[tuple[str, int]] = [(start, 0)]
    seen: set[str] = {start}
    saved: set[str] = set()
    visited = 0
    while queue:
        if len(result.pages) >= max_pages:
            result.reached_limit = True
            break
        url, d = queue.pop(0)
        if robots is not None and not robots.can_fetch(USER_AGENT, url):
            result.skipped_robots += 1
            continue
        if visited and wait > 0:
            time.sleep(wait)
        visited += 1
        try:
            res = fetch(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            )
        except NodeError as exc:
            result.failed.append((url, exc.message))
            continue
        status = int(res.get("status", 0))
        ctype = str((res.get("headers") or {}).get("content-type", "")).lower()
        body = res.get("body")
        if status >= 400:
            result.failed.append((url, f"주소가 열리지 않아요({status})."))
            continue
        if not isinstance(body, str) or (ctype and "html" not in ctype and "xml" not in ctype):
            result.skipped_other += 1
            continue
        # 쪽이 알려 준 정규 주소로 한 번 더 중복을 거른다
        cm = _CANON.search(body)
        key = url
        if cm:
            try:
                cand = canonical(cm.group(1), url)
                if host_key(urlsplit(cand).hostname or "") == start_host:
                    key = cand
            except ValueError:
                pass
        links = extract_links(body, url) if d < depth else []
        if key in saved:
            result.skipped_other += 1
        else:
            title, text = page_text(body)
            if len(text.strip()) < MIN_TEXT_CHARS:
                result.skipped_other += 1
            else:
                saved.add(key)
                result.pages.append(
                    Page(
                        url=key,
                        title=title or key,
                        text=text,
                        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
                if on_progress:
                    on_progress(len(result.pages), max_pages)
        for link in links:
            if link in seen:
                continue
            lp = urlsplit(link)
            if lp.scheme not in ("http", "https"):
                continue
            if host_key(lp.hostname or "") != start_host:
                continue
            if lp.path.lower().endswith(SKIP_EXT):
                continue
            if not allowed(link, inc, skip):
                continue
            seen.add(link)
            queue.append((link, d + 1))
    return result
