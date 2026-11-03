"""라우터 공통 도우미."""

import ipaddress
import json
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from api.config import get_settings


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def sse_frame(event: str, data: Any) -> str:
    payload = json.dumps(
        jsonable_encoder(data, custom_encoder={Decimal: float}),
        ensure_ascii=False,
        default=_default,
    )
    return f"event: {event}\ndata: {payload}\n\n"


def sse_response(frames: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _is_trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip().strip("[]"))
    except ValueError:
        return False
    return any(addr in n for n in _trusted_networks(get_settings().genio_trusted_proxies))


def client_ip(request: Request) -> str:
    """요청한 사람의 IP. X-Forwarded-For는 믿을 수 있는 프록시(nginx·tailscale 등)를
    거쳐 온 경우에만 쓰고, 오른쪽부터 처음 만나는 믿을 수 없는 주소를 고른다.
    클라이언트가 헤더를 꾸며 보내도 속도 제한을 피할 수 없다(부하 시험 보고서 §4)."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted(peer):
        return peer
    fwd = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in fwd.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop):
            return hop
    return hops[0] if hops else peer


def public_origin(request: Request) -> str:
    """공유·초대 링크에 쓸 웹 주소.

    GENIO_PUBLIC_WEB_URL에 외부 주소(Tailscale 등)를 정했으면 늘 그것을 쓴다.
    그래야 localhost 화면에서 배포해도 다른 사람이 열 수 있는 링크가 나온다.
    정하지 않았으면(localhost) 브라우저가 보낸 Origin을 쓴다.
    """
    configured = get_settings().genio_public_web_url.rstrip("/")
    host = urlparse(configured).hostname or ""
    if configured and host not in ("localhost", "127.0.0.1"):
        return configured
    origin = request.headers.get("origin")
    if origin and origin.startswith(("http://", "https://")):
        return origin.rstrip("/")
    fwd_host = request.headers.get("x-forwarded-host")
    if fwd_host:
        proto = request.headers.get("x-forwarded-proto", "https")
        return f"{proto}://{fwd_host}"
    return configured
