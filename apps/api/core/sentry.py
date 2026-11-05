"""오류 수집(Sentry, 선택). SENTRY_DSN이 비어 있으면 아무것도 하지 않는다(v0.8, ADR 0012).

보내기 전에 사용자·요청 정보를 모두 떼고, 남은 글에서 토큰·키·비밀번호처럼 보이는 값을 가린다.
- send_default_pii=False, 요청 본문 전송 안 함, 지역 변수 전송 안 함.
- 이 서버의 error_events(관리 > 시스템 상태)와 따로 동작한다. Sentry가 꺼져 있어도 기록은 남는다.
"""

import logging
from typing import Any

from api.config import get_settings
from api.services.error_log import redact

log = logging.getLogger("genio.sentry")

# 요청에서 통째로 지우는 칸(헤더·쿠키·본문·쿼리에는 토큰·개인정보가 들어 있을 수 있다)
_REQUEST_DROP = ("headers", "cookies", "data", "query_string", "env", "url")
_MAX_DEPTH = 8


def _clean(value: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v, depth + 1) for k, v in value.items()}
    return value


def scrub_event(event: Any, hint: Any = None) -> Any:
    """Sentry before_send: 개인·요청 정보를 떼고 글 속 비밀값을 가린 이벤트를 돌려준다."""
    event.pop("user", None)
    event.pop("server_name", None)
    req = event.get("request")
    if isinstance(req, dict):
        for key in _REQUEST_DROP:
            req.pop(key, None)
    for frame_holder in (event.get("exception") or {}).get("values", []) or []:
        for frame in (frame_holder.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)  # 지역 변수에는 비밀이 들어 있을 수 있다
    return _clean(event)


def scrub_breadcrumb(crumb: Any, hint: Any = None) -> Any:
    # HTTP 호출 기록에는 주소(쿼리의 키)가 들어 있어 통째로 버린다
    if crumb.get("category") in ("httplib", "http", "httpx"):
        return None
    return _clean(crumb)


def init_sentry(component: str) -> bool:
    """DSN이 있으면 Sentry를 켠다. 켰으면 True."""
    st = get_settings()
    dsn = st.sentry_dsn.strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - 설치 누락
        log.warning("SENTRY_DSN이 있지만 sentry-sdk가 설치되어 있지 않아요.")
        return False
    release = st.genio_version if st.genio_version not in ("", "dev") else None
    sentry_sdk.init(
        dsn=dsn,
        environment=st.genio_env,
        release=release,
        send_default_pii=False,
        traces_sample_rate=max(0.0, min(st.sentry_traces_sample_rate, 1.0)),
        max_request_body_size="never",
        include_local_variables=False,
        server_name="genio",
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
    )
    sentry_sdk.set_tag("component", component)
    log.info("Sentry 오류 수집을 켰어요(%s)", component)
    return True
