"""Email(SMTP) 커넥터. 플랫폼의 net.send_mail로만 보낸다(공개 메일 서버만 허용)."""

import re
from typing import Any

from nodes.spec import NodeError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def send_email(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    to = [a.strip() for a in str(params["to"]).replace(";", ",").split(",") if a.strip()]
    bad = [a for a in to if not EMAIL_RE.match(a)]
    if not to or bad:
        raise NodeError("받는 사람 메일 주소 형식이 올바르지 않아요: " + ", ".join(bad or ["(비어 있음)"]))
    try:
        port = int(secrets.get("port", 587))
    except (TypeError, ValueError) as exc:
        raise NodeError("메일 서버 포트는 숫자여야 해요. 연결 정보를 확인하세요.") from exc
    return net.send_mail(
        host=str(secrets.get("host", "")),
        port=port,
        username=str(secrets.get("username", "")),
        password=str(secrets.get("password", "")),
        sender=str(secrets.get("sender", "")),
        to=to,
        subject=str(params["subject"]),
        body=str(params["body"]),
    )
