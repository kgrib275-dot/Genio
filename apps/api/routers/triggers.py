"""자동 실행(트리거) 관리: 웹훅·예약·서비스 이벤트 만들기·고치기·토큰 다시 만들기·지금 실행(ADR 0008, v0.9)."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core.audit import audit
from api.core.crypto import encrypt_str
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import App, AppTrigger
from api.routers.common import public_origin
from api.routers.workspaces import run_dict
from api.services import service_events as sev
from api.services import triggers as svc
from api.services.queue import enqueue_run

router = APIRouter(tags=["triggers"])
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]
AppEditors = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
TriggerEditors = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="trigger"))]

MAX_TRIGGERS_PER_APP = 20


def _out(ctx: Ctx, request: Request, t: AppTrigger) -> dict[str, Any]:
    origin = public_origin(request) if ctx.role in EDIT_APPS else None
    return svc.trigger_dict(t, origin)


def _get(ctx: Ctx, trigger_id: str) -> AppTrigger:
    t = ctx.db.get(AppTrigger, trigger_id)
    if t is None:
        raise not_found("자동 실행")
    return t


@router.get("/apps/{app_id}/triggers")
def list_triggers(app_id: str, request: Request, ctx: AppViewers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(AppTrigger).where(AppTrigger.app_id == app_id).order_by(AppTrigger.created_at)
    )
    return [_out(ctx, request, t) for t in rows]


@router.get("/apps/{app_id}/service-presets")
def service_presets(app_id: str, ctx: AppEditors) -> list[dict[str, Any]]:
    """서비스 이벤트로 시작하기: 서비스별 설정 안내·이벤트 칩·샘플 받은 값."""
    del app_id, ctx
    return [sev.preset_dict(p) for p in sev.PRESETS.values()]


class TriggerIn(BaseModel):
    kind: Literal["webhook", "schedule", "service"]
    name: str = Field(default="", max_length=100)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    # 서비스가 정해 준 비밀값(Slack 서명 비밀값, Shopify 앱 비밀 키)을 붙여 넣을 때만 쓴다
    secret: str | None = Field(default=None, max_length=300)


def _default_name(kind: str, config: dict[str, Any]) -> str:
    if kind == "webhook":
        return "외부에서 받기"
    if kind == "service":
        return f"{sev.preset_of(config.get('service')).name} 이벤트"
    return "예약"


@router.post("/apps/{app_id}/triggers", status_code=201)
def create_trigger(
    app_id: str, body: TriggerIn, request: Request, ctx: AppEditors
) -> dict[str, Any]:
    app = ctx.db.get(App, app_id)
    if app is None:
        raise not_found("앱")
    count = len(list(ctx.db.scalars(select(AppTrigger.id).where(AppTrigger.app_id == app_id))))
    if count >= MAX_TRIGGERS_PER_APP:
        raise AppError(
            409,
            f"앱 하나에 자동 실행은 {MAX_TRIGGERS_PER_APP}개까지 만들 수 있어요.",
            "쓰지 않는 자동 실행을 지운 뒤 다시 만드세요.",
        )
    t = AppTrigger(
        app_id=app_id,
        kind=body.kind,
        name=body.name.strip() or _default_name(body.kind, body.config),
        enabled=body.enabled,
        config=svc.clean_config(body.kind, body.config),
        token=svc.new_token() if body.kind in ("webhook", "service") else None,
        created_by=ctx.user.id,
    )
    svc.refresh_next_run(t)
    secret: str | None
    if t.kind == "service":
        # 서비스 이벤트는 늘 서명을 확인한다. 비밀값은 제니오가 만들거나(GitHub 등) 서비스 것을 받는다(Slack 등)
        preset = sev.preset_of((t.config or {}).get("service"))
        if preset.key_origin == "provider":
            given = (body.secret or "").strip()
            if len(given) < 8:
                raise AppError(
                    422,
                    f"{preset.key_label}을(를) 붙여 넣어 주세요.",
                    f"{preset.name} 설정 화면에서 복사한 값이에요. 이 값으로 받은 알림이 진짜인지 확인해요.",
                )
            t.secret_encrypted = encrypt_str(given).decode()
            secret = None
        else:
            secret = svc.set_secret(t)
    else:
        # 서명을 켜고 만들면 비밀값을 바로 만들어 이번 응답에서 한 번만 보여 준다
        secret = svc.set_secret(t) if (t.config or {}).get("require_signature") else None
    ctx.db.add(t)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="trigger.create",
        target_type="app",
        target_id=app_id,
        meta={"kind": body.kind, "name": t.name},
    )
    ctx.db.commit()
    out = _out(ctx, request, t)
    if secret:
        out["secret"] = secret
    return out


class TriggerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    config: dict[str, Any] | None = None


@router.patch("/triggers/{trigger_id}")
def update_trigger(
    trigger_id: str, body: TriggerPatch, request: Request, ctx: TriggerEditors
) -> dict[str, Any]:
    t = _get(ctx, trigger_id)
    if body.name is not None:
        t.name = body.name.strip() or t.name
    if body.enabled is not None:
        t.enabled = body.enabled
    if body.config is not None:
        t.config = svc.clean_config(t.kind, {**(t.config or {}), **body.config})
    secret = (
        svc.set_secret(t)
        if (t.config or {}).get("require_signature") and not t.secret_encrypted
        else None
    )
    svc.refresh_next_run(t)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="trigger.update",
        target_type="app",
        target_id=t.app_id,
        meta={"kind": t.kind, "name": t.name, "enabled": t.enabled},
    )
    ctx.db.commit()
    out = _out(ctx, request, t)
    if secret:
        out["secret"] = secret
    return out


@router.post("/triggers/{trigger_id}/rotate-token")
def rotate_token(trigger_id: str, request: Request, ctx: TriggerEditors) -> dict[str, Any]:
    t = _get(ctx, trigger_id)
    if t.kind not in ("webhook", "service"):
        raise AppError(
            409,
            "예약에는 주소가 없어요.",
            "외부에서 받기·서비스 이벤트에서만 주소를 다시 만들 수 있어요.",
        )
    t.token = svc.new_token()
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="trigger.rotate_token",
        target_type="app",
        target_id=t.app_id,
        meta={"name": t.name},
    )
    ctx.db.commit()
    return _out(ctx, request, t)


@router.post("/triggers/{trigger_id}/run-now", status_code=201)
def run_now(trigger_id: str, ctx: TriggerEditors) -> dict[str, Any]:
    t = _get(ctx, trigger_id)
    inp = dict((t.config or {}).get("input") or {}) if t.kind == "schedule" else {}
    run = svc.create_trigger_run(ctx.db, t, inp, created_by=ctx.user.id)
    enqueue_run(run.id)
    ctx.db.expire_all()
    fresh = ctx.db.get(type(run), run.id)
    return run_dict(fresh or run)


@router.delete("/triggers/{trigger_id}", status_code=204)
def delete_trigger(trigger_id: str, ctx: TriggerEditors) -> Response:
    t = _get(ctx, trigger_id)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="trigger.delete",
        target_type="app",
        target_id=t.app_id,
        meta={"kind": t.kind, "name": t.name},
    )
    ctx.db.delete(t)
    ctx.db.commit()
    return Response(status_code=204)


# ---------------- 외부에서 받기: 서명 비밀값·받은 값 ----------------
class SecretIn(BaseModel):
    secret: str | None = Field(default=None, max_length=300)


@router.post("/triggers/{trigger_id}/secret")
def rotate_secret(
    trigger_id: str, request: Request, ctx: TriggerEditors, body: SecretIn | None = None
) -> dict[str, Any]:
    """서명 비밀값을 새로 만든다. 원문은 이 응답에서 한 번만 보여 준다.
    서비스가 정해 주는 비밀값(Slack·Shopify)은 새로 만들지 않고 body.secret으로 바꿔 넣는다."""
    t = _get(ctx, trigger_id)
    if t.kind not in ("webhook", "service"):
        raise AppError(
            409,
            "예약에는 서명이 필요 없어요.",
            "외부에서 받기·서비스 이벤트에서만 서명을 쓸 수 있어요.",
        )
    if (
        t.kind == "service"
        and sev.preset_of((t.config or {}).get("service")).key_origin == "provider"
    ):
        given = ((body.secret if body else None) or "").strip()
        if len(given) < 8:
            raise AppError(
                422,
                "서비스에서 받은 비밀값을 붙여 넣어 주세요.",
                "이 서비스는 비밀값을 서비스 쪽에서 정해서, 제니오가 새로 만들 수 없어요.",
            )
        t.secret_encrypted = encrypt_str(given).decode()
        audit(
            ctx.db,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user.id,
            action="trigger.rotate_secret",
            target_type="app",
            target_id=t.app_id,
            meta={"name": t.name},
        )
        ctx.db.commit()
        return {**_out(ctx, request, t), "secret": None}
    raw = svc.set_secret(t)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="trigger.rotate_secret",
        target_type="app",
        target_id=t.app_id,
        meta={"name": t.name},
    )
    ctx.db.commit()
    return {**_out(ctx, request, t), "secret": raw}


@router.get("/triggers/{trigger_id}/payloads")
def list_payloads(trigger_id: str, ctx: TriggerEditors) -> list[dict[str, Any]]:
    """최근 받은 값 5개(인증·서명 헤더는 빼고 저장)."""
    t = _get(ctx, trigger_id)
    return list(t.last_payloads or [])


@router.post("/triggers/{trigger_id}/test-sample", status_code=201)
def test_sample(trigger_id: str, ctx: TriggerEditors) -> dict[str, Any]:
    """서비스 이벤트를 '샘플 받은 값'으로 시험한다(서명 확인은 건너뛰고, 값 연결·이벤트 읽기는 그대로)."""
    t = _get(ctx, trigger_id)
    if t.kind != "service":
        raise AppError(
            409,
            "서비스 이벤트에서만 샘플로 시험할 수 있어요.",
            "외부에서 받기는 '지금 실행'을 쓰세요.",
        )
    cfg = t.config or {}
    preset = sev.preset_of(cfg.get("service"))
    headers, body = sev.sample_for(preset)
    ev = sev.parse_event(preset.key, headers, body, include_bot=True)
    run_input = sev.build_input(preset.key, ev, body, dict(cfg.get("mapping") or {}))
    run = svc.create_trigger_run(ctx.db, t, run_input, created_by=ctx.user.id)
    svc.record_payload(
        t,
        headers=headers,
        body=json.dumps(body, ensure_ascii=False).encode(),
        accepted=True,
        note="샘플로 시험",
        run_id=run.id,
    )
    ctx.db.commit()
    enqueue_run(run.id)
    ctx.db.expire_all()
    fresh = ctx.db.get(type(run), run.id)
    return {"run": run_dict(fresh or run), "input": run_input}
