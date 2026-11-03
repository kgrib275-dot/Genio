"""SSRF 방지 HTTP 호출: 사설 IP·localhost 차단, 타임아웃, 응답 크기 제한, 리다이렉트 재검사."""

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
        return host
    if host_l in ("localhost", "localhost.localdomain") or host_l.endswith(".local"):
        raise NodeError("내부 주소(localhost)는 호출할 수 없어요. 외부 공개 주소를 써 주세요.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise NodeError(
            f"'{host}' 주소를 찾지 못했어요. 철자를 확인해 주세요.", retryable=True
        ) from exc
    for info in infos:
        if _is_blocked_ip(str(info[4][0])):
            raise NodeError("사내망·내부 IP 주소는 호출할 수 없어요. 외부 공개 주소를 써 주세요.")
    return host


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
    with httpx.Client(timeout=s.genio_http_timeout_seconds, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current, allowed_domains=allowed_domains)
            kwargs: dict[str, Any] = {"headers": headers or {}}
            if form is not None:
                kwargs["data"] = form
            elif body is not None and method not in ("GET", "HEAD"):
                if isinstance(body, dict | list):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = str(body).encode("utf-8")
            try:
                with client.stream(method, current, **kwargs) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        current = urljoin(current, resp.headers["location"])
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
                            if k.lower() in ("content-type", "location", "retry-after")
                        },
                    }
            except httpx.TimeoutException as exc:
                raise NodeError("상대 서버가 제때 답하지 않았어요.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise NodeError(
                    f"요청을 보내지 못했어요: {type(exc).__name__}", retryable=True
                ) from exc
    raise NodeError("다른 주소로 너무 여러 번 넘어갔어요.")
