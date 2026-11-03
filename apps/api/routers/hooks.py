"""공개 웹훅 `/hooks/{token}` (ADR 0008). 토큰이 곧 권한이라 로그인은 필요 없다.

토큰은 비밀값처럼 다룬다: 로그·오류 문구에 남기지 않는다.
"""

import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from api.core import ratelimit
from api.core.errors import AppError
from api.db import SessionLocal
from api.models import App, AppTrigger, Run, Workspace
from api.routers.common import client_ip
from api.services import triggers as svc
from api.services.queue import enqueue_run

router = APIRouter(tags=["hooks"])

SYNC_WAIT_SECONDS = 30.0
MAX_BODY_BYTES = 256 * 1024
END_STATES = {"succeeded", "failed", "waiting_approval"}


def _not_found() -> AppError:
    return AppError(
        404,
        "이 받는 주소는 쓸 수 없어요.",
        "주소가 맞는지, 앱의 자동 실행이 켜져 있는지 확인하세요.",
    )


def _parse_body(raw: bytes, content_type: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    if len(raw) > MAX_BODY_BYTES:
        raise AppError(413, "보낸 내용이 너무 커요(256KB 초과).", "필요한 값만 담아 다시 보내세요.")
    if "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qsl

        return dict(parse_qsl(raw.decode("utf-8", "replace")))
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = raw.decode("utf-8", "replace")
        if "json" in content_type:
            raise AppError(
                400,
                "보낸 내용이 JSON 형식이 아니에요.",
                '예: {"message": "안녕하세요"} 처럼 보내세요.',
            ) from None
        return {"body": text}
    return value if isinstance(value, dict) else {"body": value}


def _rate_limited(db: Any, app: App, ip: str, trigger_id: str) -> bool:
    w = db.get(Workspace, app.workspace_id)
    limit = (w.settings or {}).get("public_rate_limit_per_minute") if w else None
    return not ratelimit.allow(f"hook:{trigger_id}:{ip}", int(limit) if limit else None)


def _start(
    token: str,
    run_input: dict[str, Any] | None,
    ip: str,
    headers: dict[str, str] | None = None,
    raw: bytes = b"",
    content_type: str = "",
    query: dict[str, str] | None = None,
) -> tuple[str, str]:
    """(run_id, mode). 서명을 켠 웹훅은 본문을 풀기 전에 서명부터 확인한다."""
    with SessionLocal() as db:
        t = db.scalar(
            select(AppTrigger).where(AppTrigger.token == token, AppTrigger.kind == "webhook")
        )
        if t is None or not t.enabled:
            raise _not_found()
        app = db.get(App, t.app_id)
        if app is None:
            raise _not_found()
        if _rate_limited(db, app, ip, t.id):
            raise AppError(
                429,
                "이 주소를 너무 자주 불렀어요.",
                "1분쯤 기다린 뒤 다시 보내거나 관리자에게 한도를 늘려 달라고 하세요.",
            )
        mode = str((t.config or {}).get("mode") or "async")
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        if (t.config or {}).get("require_signature"):
            problem = svc.verify_signature(t, hdrs, raw)
            if problem:
                svc.record_payload(t, headers=hdrs, body=raw, accepted=False, note=problem)
                db.commit()
                raise AppError(
                    401,
                    f"서명을 확인하지 못했어요: {problem}.",
                    "자동 실행 화면의 서명 비밀값으로 X-Genio-Signature를 만들어 보내세요.",
                )
        if run_input is None:
            run_input = _parse_body(raw, content_type)
            for k, v in (query or {}).items():
                run_input.setdefault(k, v)
        run = svc.create_trigger_run(db, t, run_input)
        run_id = run.id
        svc.record_payload(t, headers=hdrs, body=raw, accepted=True, run_id=run_id)
        db.commit()
    enqueue_run(run_id)
    return run_id, mode


def _result(run_id: str, wait: float) -> tuple[bool, dict[str, Any]]:
    deadline = time.time() + wait
    while True:
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            if run is None:
                raise _not_found()
            done = run.status in END_STATES
            body: dict[str, Any] = {"run_id": run.id, "status": run.status}
            if done:
                out = run.output or {}
                body["output"] = {"text": out.get("text", ""), "outputs": out.get("outputs", {})}
                if run.error:
                    body["error"] = run.error
            if done or time.time() >= deadline:
                return done, body
        time.sleep(0.3)


async def _handle(token: str, request: Request, raw: bytes) -> JSONResponse:
    if len(raw) > MAX_BODY_BYTES:
        raise AppError(413, "보낸 내용이 너무 커요(256KB 초과).", "필요한 값만 담아 다시 보내세요.")
    run_id, mode = await run_in_threadpool(
        _start,
        token,
        None,
        client_ip(request),
        dict(request.headers),
        raw,
        request.headers.get("content-type", ""),
        dict(request.query_params),
    )
    if mode != "sync":
        return JSONResponse({"run_id": run_id, "status": "queued"}, status_code=202)
    done, body = await run_in_threadpool(_result, run_id, SYNC_WAIT_SECONDS)
    return JSONResponse(json.loads(json.dumps(body, default=str)), status_code=200 if done else 202)


@router.post("/hooks/{token}")
async def hook_post(token: str, request: Request) -> JSONResponse:
    return await _handle(token, request, await request.body())


@router.get("/hooks/{token}")
async def hook_get(token: str, request: Request) -> JSONResponse:
    return await _handle(token, request, b"")
