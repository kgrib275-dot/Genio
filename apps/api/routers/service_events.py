"""서비스 이벤트 받는 주소 `/events/{token}` (v0.9, ADR 0013): Slack·GitHub·Shopify·Telegram·Jira·Typeform.

주소의 토큰과 서비스별 서명(비밀값)이 권한이다. 비밀값·토큰은 로그·오류 문구에 남기지 않는다.
Slack은 3초 안에 답해야 해서 실행은 늘 큐에 넣고 바로 돌려준다.
"""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from api.core import ratelimit
from api.core.errors import AppError
from api.db import SessionLocal
from api.models import App, AppTrigger
from api.services import service_events as sev
from api.services import triggers as svc
from api.services.queue import enqueue_run

router = APIRouter(tags=["service-events"])

MAX_BODY_BYTES = 256 * 1024
RATE_PER_MINUTE = (
    120  # 트리거 하나가 1분에 받을 수 있는 알림 수(Shopify 같은 서비스는 몰아서 보낸다)
)


def _not_found() -> AppError:
    return AppError(
        404,
        "이 받는 주소는 쓸 수 없어요.",
        "주소가 맞는지, 앱의 자동 실행이 켜져 있는지 확인하세요.",
    )


def _receive(
    token: str, headers: dict[str, str], raw: bytes, query: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    hdrs = {k.lower(): v for k, v in headers.items()}
    run_id: str | None = None
    with SessionLocal() as db:
        t = db.scalar(
            select(AppTrigger).where(AppTrigger.token == token, AppTrigger.kind == "service")
        )
        if t is None or not t.enabled or db.get(App, t.app_id) is None:
            raise _not_found()
        if not ratelimit.allow(f"event:{t.id}", RATE_PER_MINUTE):
            raise AppError(
                429,
                "이 주소로 알림이 너무 자주 와요.",
                "잠시 뒤 다시 보내 달라고 서비스 쪽 재전송 설정을 확인하세요.",
            )
        cfg = t.config or {}
        preset = sev.preset_of(cfg.get("service"))
        secret = svc.trigger_secret(t)
        body_json: Any = None
        try:
            body_json = json.loads(raw) if raw.strip() else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            body_json = None

        # Slack 주소 확인 요청: 비밀값을 아직 안 넣었으면 확인 응답만 돌려준다(실행은 만들지 않는다)
        challenge_only = (
            preset.key == "slack"
            and not secret
            and isinstance(body_json, dict)
            and body_json.get("type") == "url_verification"
        )
        if not challenge_only:
            if not secret:
                raise AppError(
                    401,
                    "서명 비밀값이 아직 없어요.",
                    f"자동 실행 화면에서 {preset.key_label}을(를) 넣은 뒤 다시 보내세요.",
                )
            problem = sev.verify(preset.key, secret, hdrs, raw, query)
            if problem:
                svc.record_payload(t, headers=hdrs, body=raw, accepted=False, note=problem)
                db.commit()
                raise AppError(
                    401,
                    f"서명을 확인하지 못했어요: {problem}.",
                    f"{preset.name}에 넣은 비밀값이 제니오 자동 실행 화면의 값과 같은지 확인하세요.",
                )
        if not isinstance(body_json, dict):
            raise AppError(
                400,
                "보낸 내용이 JSON 형식이 아니에요.",
                f"{preset.name} 웹훅 형식을 JSON(application/json)으로 바꿔 주세요.",
            )
        ev = sev.parse_event(preset.key, hdrs, body_json, bool(cfg.get("include_bot")))
        if ev.challenge is not None:
            return 200, {"challenge": ev.challenge}

        def ignore(reason: str) -> tuple[int, dict[str, Any]]:
            svc.record_payload(t, headers=hdrs, body=raw, accepted=True, note=f"걸러냄: {reason}")
            db.commit()
            return 200, {"ignored": reason}

        if ev.ignore:
            return ignore(ev.ignore)
        if not sev.passes_filter(list(cfg.get("events") or []), ev):
            return ignore("고르지 않은 이벤트라 건너뛰었어요")
        if ev.delivery_id and sev.seen_recently(f"{t.id}:{ev.delivery_id}"):
            return ignore("이미 받은 알림(다시 보내기)이라 건너뛰었어요")
        run_input = sev.build_input(preset.key, ev, body_json, dict(cfg.get("mapping") or {}))
        run = svc.create_trigger_run(db, t, run_input)
        run_id = run.id
        svc.record_payload(t, headers=hdrs, body=raw, accepted=True, run_id=run_id)
        db.commit()
    enqueue_run(run_id)
    return 202, {"run_id": run_id, "status": "queued"}


@router.post("/events/{token}")
async def receive_event(token: str, request: Request) -> JSONResponse:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise AppError(413, "보낸 내용이 너무 커요(256KB 초과).", "필요한 값만 담아 다시 보내세요.")
    status, body = await run_in_threadpool(
        _receive,
        token,
        dict(request.headers),
        raw,
        dict(request.query_params),
    )
    return JSONResponse(body, status_code=status)
