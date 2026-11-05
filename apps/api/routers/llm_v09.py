"""v0.9 AI 연결: 키 여러 개(분산·돌려쓰기), 공급자 간 자동 전환 설정과 시험."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, MANAGE_SECRETS, Ctx, require_role
from api.llm import keypool
from api.llm.base import LlmError
from api.llm.chain import ChainAdapter, effective_fallback
from api.llm.presets import is_rerank
from api.llm.registry import resolve_llm
from api.models import Workspace
from api.routers.workspaces import probe_connection
from api.services import llm_keys as svc

router = APIRouter(tags=["llm-v09"])
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


class ProviderPatch(BaseModel):
    key_strategy: str | None = Field(default=None, max_length=20)
    primary_weight: int | None = Field(default=None, ge=1, le=10)


@router.patch("/workspaces/{ws}/llm-providers/{provider_id}")
def patch_provider(
    ws: str, provider_id: str, body: ProviderPatch, ctx: SecretManagers
) -> dict[str, Any]:
    """키 돌려쓰기 방식(앞의 키부터·돌아가며·비중대로)과 기본 키의 비중."""
    row = svc.get_provider(ctx.db, ws, provider_id)
    if body.key_strategy is not None:
        svc.set_strategy(row, body.key_strategy)
    if body.primary_weight is not None:
        svc.update_key(row, "primary", weight=body.primary_weight)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_provider.update",
        target_type="llm_provider",
        target_id=row.id,
        meta={"key_strategy": row.key_strategy},
    )
    ctx.db.commit()
    return svc.provider_view(row)


class KeyIn(BaseModel):
    label: str = Field(default="", max_length=60)
    api_key: str = Field(min_length=4, max_length=500)
    weight: int = Field(default=1, ge=1, le=10)


@router.post("/workspaces/{ws}/llm-providers/{provider_id}/keys", status_code=201)
def add_key(ws: str, provider_id: str, body: KeyIn, ctx: SecretManagers) -> dict[str, Any]:
    row = svc.get_provider(ctx.db, ws, provider_id)
    key_id = svc.add_key(row, body.label, body.api_key, body.weight)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_key.add",
        target_type="llm_provider",
        target_id=row.id,
        meta={"key_id": key_id, "label": body.label[:60]},  # 키 값은 남기지 않는다
    )
    ctx.db.commit()
    return svc.provider_view(row)


class KeyPatch(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    weight: int | None = Field(default=None, ge=1, le=10)
    disabled: bool | None = None


@router.patch("/workspaces/{ws}/llm-providers/{provider_id}/keys/{key_id}")
def patch_key(
    ws: str, provider_id: str, key_id: str, body: KeyPatch, ctx: SecretManagers
) -> dict[str, Any]:
    row = svc.get_provider(ctx.db, ws, provider_id)
    svc.update_key(row, key_id, label=body.label, weight=body.weight, disabled=body.disabled)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_key.update",
        target_type="llm_provider",
        target_id=row.id,
        meta={"key_id": key_id, "disabled": body.disabled, "weight": body.weight},
    )
    ctx.db.commit()
    return svc.provider_view(row)


@router.delete("/workspaces/{ws}/llm-providers/{provider_id}/keys/{key_id}", status_code=204)
def delete_key(ws: str, provider_id: str, key_id: str, ctx: SecretManagers) -> Response:
    row = svc.get_provider(ctx.db, ws, provider_id)
    svc.delete_key(row, key_id)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_key.delete",
        target_type="llm_provider",
        target_id=row.id,
        meta={"key_id": key_id},
    )
    ctx.db.commit()
    return Response(status_code=204)


@router.post("/workspaces/{ws}/llm-providers/{provider_id}/keys/{key_id}/test")
def test_key(ws: str, provider_id: str, key_id: str, ctx: Builders) -> dict[str, Any]:
    """키 하나만 연결해 본다. 성공하면 쉬고 있던 키를 바로 다시 쓴다."""
    row = svc.get_provider(ctx.db, ws, provider_id)
    secret = svc.key_secret(row, key_id)
    out = probe_connection(row.provider, secret, row.base_url, row.default_model)
    if out.get("ok"):
        keypool.clear_cooldown(row.id, key_id)
    return out


# ---------------- 공급자 간 자동 전환 ----------------
@router.get("/workspaces/{ws}/llm-fallback")
def get_fallback(ws: str, ctx: Builders) -> dict[str, Any]:
    return svc.fallback_view(ctx.db, ws)


class LinkIn(BaseModel):
    provider_id: str = Field(min_length=1, max_length=36)
    model: str = Field(default="", max_length=100)


class FallbackIn(BaseModel):
    enabled: bool = False
    links: list[LinkIn] = Field(default_factory=list, max_length=10)
    triggers: dict[str, bool] = Field(default_factory=dict)


@router.put("/workspaces/{ws}/llm-fallback")
def put_fallback(ws: str, body: FallbackIn, ctx: SecretManagers) -> dict[str, Any]:
    cfg = svc.clean_fallback(ctx.db, ws, body.model_dump())
    wsr = ctx.db.get(Workspace, ws)
    if wsr is None:
        raise AppError(404, "워크스페이스를 찾을 수 없어요.", "목록에서 다시 골라 주세요.")
    wsr.settings = {**(wsr.settings or {}), "llm_fallback": cfg}
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_fallback.update",
        target_type="workspace",
        target_id=ws,
        meta={"enabled": cfg["enabled"], "links": len(cfg["links"])},
    )
    ctx.db.commit()
    return svc.fallback_view(ctx.db, ws)


@router.post("/workspaces/{ws}/llm-fallback/test")
def test_fallback(ws: str, ctx: SecretManagers) -> dict[str, Any]:
    """기본 연결이 실패한 것처럼 만들어(실제로 부르지는 않음) 어느 연결이 대신 답하는지 본다."""
    wsr = ctx.db.get(Workspace, ws)
    cfg = effective_fallback((wsr.settings or {}).get("llm_fallback") if wsr else None)
    if cfg is None:
        raise AppError(
            422,
            "자동 전환 순서가 아직 없어요.",
            "대체할 AI 연결을 추가하고 '자동 전환 쓰기'를 켠 뒤 시험하세요.",
        )
    # 조건 이름(outage·rate_limit…)은 LlmError.kind와 같다. 켜져 있는 첫 조건으로 실패를 흉내 낸다
    kind = next((k for k, on in cfg["triggers"].items() if on), None)
    if kind is None:
        raise AppError(
            422,
            "넘어갈 조건이 하나도 켜져 있지 않아요.",
            "서버 오류·한도 초과 같은 조건을 하나 이상 켜고 시험하세요.",
        )
    try:
        llm = resolve_llm(ctx.db, ws, "default", simulate_first_failure=kind)
    except LlmError as exc:
        raise AppError(422, exc.message, exc.hint) from None
    adapter = llm.adapter
    started = time.perf_counter()
    if not isinstance(adapter, ChainAdapter):  # 대체 연결이 모두 지워졌을 때
        raise AppError(
            422,
            "쓸 수 있는 대체 연결이 없어요.",
            "자동 전환 순서의 연결이 지워졌는지 확인하세요.",
        )
    try:
        res = adapter.complete(
            model=llm.model,
            system="시험입니다. 한 단어로만 짧게 답하세요.",
            prompt="OK 라고만 답하세요.",
            temperature=None,
            json_schema=None,
        )
    except LlmError as exc:
        return {
            "ok": False,
            "message": exc.message,
            "hint": exc.hint,
            "trail": adapter.trail,
            "notes": adapter.take_notes(),
        }
    by = adapter.answered_by
    return {
        "ok": True,
        "message": f"{by.label if by else '대체'} 연결이 대신 답했어요.",
        "hint": "",
        "answered_by": {"label": by.label, "provider": by.provider, "model": res.model}
        if by
        else None,
        "text": res.text[:100],
        "trail": adapter.trail,
        "notes": adapter.take_notes(),
        "ms": round((time.perf_counter() - started) * 1000),
        "simulated": kind,
    }


# 재정렬 전용 연결 목록(지식베이스 설정에서 고른다). 키는 없다.
@router.get("/workspaces/{ws}/rerank-connections")
def rerank_connections(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from api.models import LlmProvider

    rows = ctx.db.scalars(
        select(LlmProvider).where(LlmProvider.workspace_id == ws).order_by(LlmProvider.label)
    )
    return [
        {
            "id": r.id,
            "label": r.label,
            "provider": r.provider,
            "default_model": r.default_model,
        }
        for r in rows
        if is_rerank(r.provider)
    ]
