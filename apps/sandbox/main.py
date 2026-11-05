"""코드 실행 격리 서버(v0.8, ADR 0012).

- POST /run  {language: python|javascript, code, inputs, timeout} → {ok, result|kind+error}
- 제니오 API·워커만 부른다. 공유 비밀 키(GENIO_SANDBOX_KEY)를 X-Sandbox-Key 헤더로 받는다.
  키가 설정되지 않았으면 실행을 거절한다(열어 둔 채로 뜨지 않게).
- 이 서버는 DB·Redis·AI 키에 접근하지 않고, 컴포즈에서 외부로 나가는 네트워크가 없는 내부망에만 둔다.
"""

import hmac
import os
import threading
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from sandbox import runner

MAX_BODY_BYTES = 1024 * 1024  # 코드+입력 값 합쳐 1MB
MAX_CONCURRENT = max(1, int(os.environ.get("SANDBOX_MAX_CONCURRENT", "8") or 8))

app = FastAPI(
    title="Genio Sandbox", version="0.8.0", docs_url=None, redoc_url=None, openapi_url=None
)
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


class RunIn(BaseModel):
    language: Literal["python", "javascript"]
    code: str = Field(max_length=200_000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=10.0, ge=1, le=60)


def _key() -> str:
    return os.environ.get("GENIO_SANDBOX_KEY", "")


def _err(status: int, kind: str, error: str) -> JSONResponse:
    return JSONResponse({"ok": False, "kind": kind, "error": error}, status_code=status)


@app.get("/health")
def health() -> dict[str, str]:
    """살아 있는지만 알려 준다(설정·버전 정보 없음)."""
    return {"status": "ok"}


async def _read_limited(request: Request) -> bytes | None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


@app.post("/run")
async def run(request: Request) -> JSONResponse:
    expected = _key()
    if not expected:
        return _err(503, "config", "샌드박스 키(GENIO_SANDBOX_KEY)가 설정되지 않았어요.")
    given = request.headers.get("x-sandbox-key", "")
    # 길이가 달라도 같은 시간이 걸리게 바이트로 비교한다
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        return _err(401, "auth", "인증에 실패했어요.")
    body = await _read_limited(request)
    if body is None:
        return _err(413, "size", "요청이 너무 커요(최대 1MB).")
    try:
        req = RunIn.model_validate_json(body)
    except ValidationError:
        return _err(422, "invalid", "요청 형식이 올바르지 않아요.")
    if not _slots.acquire(blocking=False):
        return _err(429, "busy", "지금 실행 중인 코드가 너무 많아요.")
    try:
        result = await run_in_threadpool(
            runner.run_code, req.language, req.code, req.inputs, req.timeout
        )
    finally:
        _slots.release()
    return JSONResponse(result)
