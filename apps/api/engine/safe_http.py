"""SSRF 방지 HTTP 호출: 사설 IP·localhost 차단, 타임아웃, 응답 크기 제한, 리다이렉트 재검사.

운영 준비 1차(B1·F3):
- DNS 재바인딩 방지: 검사한 IP로 직접 연결한다(Host 헤더·TLS 이름은 원래 호스트). 검사와 연결 사이에
  DNS 답이 바뀌어도 내부 IP로 가지 않는다.
- 다른 호스트로 넘어갈 때(리다이렉트) 인증 헤더 등 호출한 쪽 헤더를 버리고 기본 헤더만 보낸다.
"""

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from api.config import get_settings
from nodes import NodeError

MAX_REDIRECTS = 3


def _is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (
            isinstance(addr, ipaddress.IPv4Address)
            and addr in ipaddress.ip_network("100.64.0.0/10")
        )
    )


def check_url(url: str, *, allowed_domains: list[str] | None = None) -> str:
    """막힌 주소면 NodeError. 통과하면 호스트 이름을 돌려준다."""
    return _resolve(url, allowed_domains=allowed_domains)[0]


def _resolve(url: str, *, allowed_domains: list[str] | None = None) -> tuple[str, str | None]:
    """(호스트, 연결할 IP). 사설망 허용(시험 전용)이면 IP는 None(고정하지 않음)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise NodeError("http 또는 https 주소만 호출할 수 있어요.")
    host = parsed.hostname
    if not host:
        raise NodeError("주소에서 호스트를 찾지 못했어요. 주소 형식을 확인해 주세요.")
    host_l = host.lower()
    if allowed_domains is not None and not any(
        host_l == d or host_l.endswith("." + d) for d in allowed_domains
    ):
        raise NodeError(f"'{host}'는 이 확장이 쓰겠다고 선언한 도메인이 아니에요.")
    if get_settings().genio_allow_private_network:
        return host, None
    if host_l in ("localhost", "localhost.localdomain") or host_l.endswith(".local"):
        raise NodeError("내부 주소(localhost)는 호출할 수 없어요. 외부 공개 주소를 써 주세요.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise NodeError(
            f"'{host}' 주소를 찾지 못했어요. 철자를 확인해 주세요.", retryable=True
        ) from exc
    ips = [str(info[4][0]) for info in infos]
    for ip in ips:
        if _is_blocked_ip(ip):
            raise NodeError("사내망·내부 IP 주소는 호출할 수 없어요. 외부 공개 주소를 써 주세요.")
    if not ips:
        raise NodeError(f"'{host}' 주소를 찾지 못했어요. 철자를 확인해 주세요.", retryable=True)
    return host, ips[0]


# 다른 호스트로 넘어갈 때도 그대로 보내는 헤더(그 밖의 헤더 = 인증 등은 버린다)
SAFE_CROSS_HOST_HEADERS = {"accept", "accept-language", "content-type", "user-agent"}


def _prepare(
    url: str, headers: dict[str, str], allowed_domains: list[str] | None
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    """검사한 IP로 직접 가는 (주소, 헤더, 확장, 원래 호스트)."""
    host, ip = _resolve(url, allowed_domains=allowed_domains)
    if ip is None:
        return url, headers, {}, host
    parsed = urlparse(url)
    ip_host = f"[{ip}]" if ":" in ip else ip
    netloc = ip_host + (f":{parsed.port}" if parsed.port else "")
    pinned = parsed._replace(netloc=netloc).geturl()
    host_header = host + (f":{parsed.port}" if parsed.port else "")
    out = {k: v for k, v in headers.items() if k.lower() != "host"}
    out["Host"] = host_header
    ext: dict[str, Any] = {"sni_hostname": host} if parsed.scheme == "https" else {}
    return pinned, out, ext, host


def _next_headers(headers: dict[str, str], from_host: str, to_url: str) -> dict[str, str]:
    to_host = (urlparse(to_url).hostname or "").lower()
    if to_host == from_host.lower():
        return headers
    return {k: v for k, v in headers.items() if k.lower() in SAFE_CROSS_HOST_HEADERS}


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    allowed_domains: list[str] | None = None,
    form: dict[str, str] | None = None,
) -> dict[str, Any]:
    s = get_settings()
    limit = s.genio_http_max_response_bytes
    current = url
    hdrs = dict(headers or {})
    with httpx.Client(timeout=s.genio_http_timeout_seconds, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target, sent, ext, host = _prepare(current, hdrs, allowed_domains)
            kwargs: dict[str, Any] = {"headers": sent, "extensions": ext}
            if form is not None:
                kwargs["data"] = form
            elif body is not None and method not in ("GET", "HEAD"):
                if isinstance(body, dict | list):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = str(body).encode("utf-8")
            try:
                with client.stream(method, target, **kwargs) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        nxt = urljoin(current, resp.headers["location"])
                        hdrs = _next_headers(hdrs, host, nxt)
                        current = nxt
                        continue
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise NodeError(
                                f"응답이 너무 커요(최대 {limit // 1024}KB). 더 작은 범위를 요청해 주세요."
                            )
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    text = raw.decode(resp.encoding or "utf-8", errors="replace")
                    parsed: Any
                    try:
                        parsed = json.loads(text) if text else None
                    except json.JSONDecodeError:
                        parsed = text
                    if resp.status_code >= 500:
                        raise NodeError(
                            f"상대 서버 오류({resp.status_code})가 났어요. 잠시 후 다시 시도해요.",
                            retryable=True,
                        )
                    return {
                        "status": resp.status_code,
                        "body": parsed,
                        "headers": {
                            k: v
                            for k, v in resp.headers.items()
                            if k.lower()
                            in ("content-type", "location", "retry-after", "mcp-session-id")
                        },
                    }
            except httpx.TimeoutException as exc:
                raise NodeError("상대 서버가 제때 답하지 않았어요.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise NodeError(
                    f"요청을 보내지 못했어요: {type(exc).__name__}", retryable=True
                ) from exc
    raise NodeError("다른 주소로 너무 여러 번 넘어갔어요.")


def fetch_raw(
    url: str,
    *,
    max_bytes: int,
    allowed_domains: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """파일·문서를 바이트 그대로 받는다(4xx도 돌려줘서 호출한 쪽이 이유를 안내할 수 있다).

    사설망 차단·리다이렉트 재검사·크기 제한은 request와 같다. 돌려주는 값:
    {"status": int, "body": bytes, "headers": {content-type, content-disposition, location}}
    """
    s = get_settings()
    current = url
    hdrs = dict(headers or {})
    with httpx.Client(timeout=s.genio_http_timeout_seconds, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target, sent, ext, host = _prepare(current, hdrs, allowed_domains)
            try:
                with client.stream("GET", target, headers=sent, extensions=ext) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        nxt = urljoin(current, resp.headers["location"])
                        hdrs = _next_headers(hdrs, host, nxt)
                        current = nxt
                        continue
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise NodeError(
                                f"파일이 너무 커요(최대 {max_bytes // (1024 * 1024)}MB). "
                                "더 작은 문서를 써 주세요."
                            )
                        chunks.append(chunk)
                    if resp.status_code >= 500:
                        raise NodeError(
                            f"상대 서버 오류({resp.status_code})가 났어요. 잠시 후 다시 시도해요.",
                            retryable=True,
                        )
                    return {
                        "status": resp.status_code,
                        "body": b"".join(chunks),
                        "headers": {
                            k: v
                            for k, v in resp.headers.items()
                            if k.lower() in ("content-type", "content-disposition", "location")
                        },
                    }
            except httpx.TimeoutException as exc:
                raise NodeError("상대 서버가 제때 답하지 않았어요.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise NodeError(
                    f"파일을 받지 못했어요: {type(exc).__name__}", retryable=True
                ) from exc
    raise NodeError("다른 주소로 너무 여러 번 넘어갔어요.")


def fetch_bytes(url: str, *, max_bytes: int) -> bytes:
    """공개 주소에서 파일(이미지 등)을 그대로 받는다. 사설망 차단·리다이렉트 재검사·크기 제한 동일."""
    s = get_settings()
    current = url
    with httpx.Client(timeout=s.genio_http_timeout_seconds, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target, sent, ext, _host = _prepare(current, {}, None)
            try:
                with client.stream("GET", target, headers=sent, extensions=ext) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        current = urljoin(current, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        raise NodeError(
                            f"이미지 주소에서 파일을 받지 못했어요({resp.status_code}). "
                            "주소가 공개돼 있는지 확인해 주세요."
                        )
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise NodeError(
                                f"파일이 너무 커요(최대 {max_bytes // (1024 * 1024)}MB). "
                                "더 작은 파일 주소를 써 주세요."
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.TimeoutException as exc:
                raise NodeError("상대 서버가 제때 답하지 않았어요.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise NodeError(
                    f"파일을 받지 못했어요: {type(exc).__name__}", retryable=True
                ) from exc
    raise NodeError("다른 주소로 너무 여러 번 넘어갔어요.")
