"""배포 주소의 IP 접근 제한(v0.8): 허용한 IP·대역(CIDR)에서만 공개 주소를 열 수 있다.

- 비어 있으면 제한이 없다(기본).
- 요청한 사람의 IP는 `routers/common.client_ip`로 구한다. 믿을 수 있는 프록시가 붙인
  X-Forwarded-For만 따르므로, 헤더를 꾸며 보내도 우회할 수 없다.
- 막힐 때는 허용 목록을 알려 주지 않는다.
"""

import ipaddress
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import Deployment

MAX_ENTRIES = 50
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _network(entry: str) -> Network:
    return ipaddress.ip_network(entry.strip(), strict=False)


def normalize(entries: list[str]) -> list[str]:
    """입력한 주소를 점검해 정리한다(공백 제거, 중복 제거, 한 대 주소는 /32 없이). 틀리면 두 줄 오류."""
    out: list[str] = []
    for raw in entries:
        text = str(raw).strip()
        if not text:
            continue
        try:
            net = _network(text)
        except ValueError:
            raise AppError(
                422,
                f"'{text[:60]}'은(는) 올바른 IP 주소가 아니에요.",
                "예: 203.0.113.7 또는 203.0.113.0/24, 2001:db8::/32 처럼 적어 주세요.",
            ) from None
        item = str(net.network_address) if net.prefixlen == net.max_prefixlen else str(net)
        if item not in out:
            out.append(item)
    if len(out) > MAX_ENTRIES:
        raise AppError(
            422,
            f"허용 주소는 최대 {MAX_ENTRIES}개까지 넣을 수 있어요.",
            "넓은 대역(CIDR) 하나로 묶어서 줄여 주세요.",
        )
    return out


def _addr(ip: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        addr = ipaddress.ip_address(ip.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped  # ::ffff:1.2.3.4 는 IPv4로 본다
    return addr


def ip_allowed(ip: str, entries: list[str] | None) -> bool:
    """entries가 비어 있으면 누구나 허용. 주소를 알 수 없으면(unknown 등) 제한이 있을 때는 거절."""
    if not entries:
        return True
    addr = _addr(ip)
    if addr is None:
        return False
    for entry in entries:
        try:
            net = _network(entry)
        except ValueError:
            continue
        if addr.version == net.version and addr in net:
            return True
    return False


def blocked_error() -> AppError:
    return AppError(
        403,
        "이 주소에서는 이 앱을 열 수 없어요.",
        "허용된 네트워크(예: 회사 내부망)에서 다시 열어 보세요. 계속 안 되면 앱 관리자에게 문의하세요.",
    )


def allowed_ips_of(db: Session, token: str) -> list[str]:
    row: Any = db.scalar(select(Deployment.allowed_ips).where(Deployment.public_token == token))
    return [str(x) for x in (row or [])]
