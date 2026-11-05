"""코드 실행 격리 서버 호출(v0.8, ADR 0012).

GENIO_SANDBOX_URL이 설정되어 있으면 코드 단계(파이썬·자바스크립트)를 별도 컨테이너의 샌드박스 서버에서 실행한다.
비워 두면(기본) 지금처럼 서버 안에서 실행한다(code_runner·js_runner).

샌드박스 주소는 운영자가 정하는 내부 주소라서 safe_http(사설망 차단)를 거치지 않는다.
사용자가 입력한 주소는 절대 쓰지 않는다. 키는 오류·로그에 남기지 않는다.
"""

from typing import Any

import httpx

from api.config import get_settings
from nodes import NodeError

# 단계 제한 시간에 더하는 여유(네트워크·프로세스 시작 시간)
MARGIN_SECONDS = 5.0


def enabled() -> bool:
    return bool(get_settings().genio_sandbox_url.strip())


def _fail(message: str, hint: str) -> NodeError:
    return NodeError(f"{message} {hint}")


def run_remote(language: str, code: str, inputs: dict[str, Any], timeout: float) -> dict[str, Any]:
    """샌드박스 서버에서 코드를 실행하고 결과 dict를 돌려준다. 실패하면 두 줄짜리 NodeError."""
    st = get_settings()
    url = st.genio_sandbox_url.strip().rstrip("/") + "/run"
    payload = {"language": language, "code": code, "inputs": inputs, "timeout": timeout}
    try:
        with httpx.Client(timeout=timeout + MARGIN_SECONDS, follow_redirects=False) as client:
            res = client.post(url, json=payload, headers={"X-Sandbox-Key": st.genio_sandbox_key})
    except httpx.TimeoutException:
        raise _fail(
            "코드 실행 서버가 제때 답하지 않았어요.",
            "반복문이 끝나는지 확인하고, 계속되면 관리자에게 코드 실행 서버 점검을 요청하세요.",
        ) from None
    except httpx.HTTPError:
        raise _fail(
            "코드 실행 서버에 연결하지 못했어요.",
            "잠시 뒤 다시 시도하고, 계속되면 관리자에게 코드 실행 서버 상태 확인을 요청하세요.",
        ) from None

    if res.status_code in (401, 403):
        raise _fail(
            "코드 실행 서버가 요청을 받아 주지 않았어요.",
            "관리자에게 GENIO_SANDBOX_KEY 설정이 서버와 같은지 확인해 달라고 요청하세요.",
        )
    if res.status_code == 413:
        raise _fail("코드나 입력 값이 너무 커요.", "코드와 입력 값을 합쳐 1MB 아래로 줄여 주세요.")
    if res.status_code == 429:
        raise _fail("코드 실행 서버가 지금 바빠요.", "잠시 뒤 다시 실행해 주세요.")
    if res.status_code >= 500 and res.status_code != 503:
        raise _fail(
            "코드 실행 서버에 문제가 생겼어요.",
            "잠시 뒤 다시 시도하고, 계속되면 관리자에게 알려 주세요.",
        )
    try:
        data = res.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise _fail(
            "코드 실행 서버의 답을 읽지 못했어요.",
            "관리자에게 코드 실행 서버 주소 설정 확인을 요청하세요.",
        )
    if data.get("ok"):
        result = data.get("result")
        return result if isinstance(result, dict) else {"value": result}

    kind = str(data.get("kind") or "error")
    error = str(data.get("error") or "알 수 없는 오류")[:300]
    if kind == "timeout":
        raise _fail(
            f"코드가 {timeout:.0f}초 안에 끝나지 않았어요.", "반복문이 끝나는지 확인해 주세요."
        )
    if kind == "memory":
        raise _fail("코드가 메모리를 너무 많이 써서 멈췄어요.", "큰 목록이나 반복을 줄여 주세요.")
    if kind == "output":
        raise _fail("코드 결과가 너무 커요.", "결과를 1MB 아래로 줄여 주세요.")
    if kind == "config":
        raise _fail(
            "코드 실행 서버 설정이 끝나지 않았어요.",
            "관리자에게 GENIO_SANDBOX_KEY 설정을 요청하세요.",
        )
    if language == "javascript":
        raise _fail(f"자바스크립트 코드에서 오류가 났어요: {error}.", "코드를 확인해 주세요.")
    raise _fail(f"코드 실행 중 오류: {error}.", "코드를 확인해 주세요.")


def health() -> tuple[bool, float]:
    """(응답 여부, 걸린 ms). 상태 화면용. 인증 없이 /health만 부른다."""
    import time

    url = get_settings().genio_sandbox_url.strip().rstrip("/") + "/health"
    t = time.perf_counter()
    try:
        res = httpx.get(url, timeout=2.0, follow_redirects=False)
        ok = res.status_code == 200
    except httpx.HTTPError:
        ok = False
    return ok, round((time.perf_counter() - t) * 1000, 1)
