"""자동 실행(트리거) 관리: 웹훅·예약 만들기·고치기·토큰 다시 만들기·지금 실행(ADR 0008)."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import App, AppTrigger
from api.routers.common import public_origin
from api.routers.workspaces import run_dict
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


class TriggerIn(BaseModel):
    kind: Literal["webhook", "schedule"]
    name: str = Field(default="", max_length=100)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


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
        name=body.name.strip() or ("외부에서 받기" if body.kind == "webhook" else "예약"),
        enabled=body.enabled,
        config=svc.clean_config(body.kind, body.config),
        token=svc.new_token() if body.kind == "webhook" else None,
        created_by=ctx.user.id,
    )
    svc.refresh_next_run(t)
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
    if t.kind != "webhook":
        raise AppError(
            409, "예약에는 주소가 없어요.", "외부에서 받기에서만 주소를 다시 만들 수 있어요."
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
@router.post("/triggers/{trigger_id}/secret")
def rotate_secret(trigger_id: str, request: Request, ctx: TriggerEditors) -> dict[str, Any]:
    """서명 비밀값을 새로 만든다. 원문은 이 응답에서 한 번만 보여 준다."""
    t = _get(ctx, trigger_id)
    if t.kind != "webhook":
        raise AppError(
            409, "예약에는 서명이 필요 없어요.", "외부에서 받기에서만 서명을 쓸 수 있어요."
        )
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
