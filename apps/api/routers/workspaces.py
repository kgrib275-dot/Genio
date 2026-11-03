"""워크스페이스: 멤버·초대·역할, AI 연결(LLM 키), 노드 카탈로그, 템플릿, 운영(실행 이력·사용량·감사 로그)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select

from api.core.audit import audit
from api.core.crypto import decrypt_str, encrypt_str, mask
from api.core.errors import AppError, not_found
from api.core.security import random_token
from api.deps import (
    ANY_MEMBER,
    EDIT_APPS,
    MANAGE_MEMBERS,
    MANAGE_SECRETS,
    VIEW_RUNS,
    Ctx,
    Role,
    require_role,
)
from api.llm.registry import PROVIDERS
from api.market import service as market
from api.models import App, AuditLog, Invitation, LlmProvider, Membership, Run, User
from api.routers.common import public_origin
from api.schemas.graph import Graph
from api.services.projects import hidden_project_ids
from nodes import registry

router = APIRouter(tags=["workspaces"])

Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
Viewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]


# ---------------- 멤버·초대 ----------------
def _member(m: Membership, u: User) -> dict[str, Any]:
    return {"id": m.id, "user_id": u.id, "email": u.email, "name": u.name, "role": m.role}


@router.get("/workspaces/{ws}/members")
def list_members(ws: str, ctx: Members) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == ws)
    ).all()
    order = {"owner": 0, "admin": 1, "builder": 2, "operator": 3, "member": 4}
    return sorted(
        (_member(m, u) for m, u in rows), key=lambda x: (order.get(x["role"], 9), x["email"])
    )


class InviteIn(BaseModel):
    email: EmailStr
    role: Role


def _invitation(inv: Invitation, origin: str) -> dict[str, Any]:
    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "token": inv.token,
        "expires_at": inv.expires_at,
        "accepted_at": inv.accepted_at,
        "accept_url": f"{origin}/invite/{inv.token}",
    }


@router.post("/workspaces/{ws}/invitations")
def invite(ws: str, body: InviteIn, request: Request, ctx: Managers) -> dict[str, Any]:
    if body.role == "owner" and ctx.role != "owner":
        raise AppError(403, "owner 역할로는 owner만 초대할 수 있어요.", "다른 역할을 고르세요.")
    inv = Invitation(
        workspace_id=ws,
        email=body.email.lower(),
        role=body.role,
        token=random_token(),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    ctx.db.add(inv)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="member.invite",
        target_type="invitation",
        target_id=inv.email,
        meta={"role": body.role},
    )
    ctx.db.commit()
    return _invitation(inv, public_origin(request))


@router.get("/workspaces/{ws}/invitations")
def list_invitations(ws: str, request: Request, ctx: Managers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(Invitation)
        .where(Invitation.workspace_id == ws)
        .order_by(Invitation.expires_at.desc())
    )
    origin = public_origin(request)
    return [_invitation(i, origin) for i in rows]


class RoleIn(BaseModel):
    role: Role


@router.patch("/workspaces/{ws}/members/{member_id}")
def change_role(ws: str, member_id: str, body: RoleIn, ctx: Managers) -> dict[str, Any]:
    m = ctx.db.get(Membership, member_id)
    if m is None or m.workspace_id != ws:
        raise not_found("멤버")
    if (m.role == "owner" or body.role == "owner") and ctx.role != "owner":
        raise AppError(
            403, "owner 역할은 owner만 바꿀 수 있어요.", "워크스페이스 owner에게 요청하세요."
        )
    if m.role == "owner" and body.role != "owner":
        owners = ctx.db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == ws, Membership.role == "owner")
        )
        if (owners or 0) <= 1:
            raise AppError(
                409, "마지막 owner의 역할은 바꿀 수 없어요.", "다른 멤버를 먼저 owner로 지정하세요."
            )
    before = m.role
    m.role = body.role
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="member.role_change",
        target_type="membership",
        target_id=m.id,
        meta={"from": before, "to": body.role},
    )
    ctx.db.commit()
    user = ctx.db.get(User, m.user_id)
    if user is None:
        raise not_found("멤버")
    return _member(m, user)


# ---------------- AI 연결 ----------------
def _provider(p: LlmProvider) -> dict[str, Any]:
    try:
        masked = mask(decrypt_str(p.api_key_encrypted))
    except ValueError:
        masked = "****"
    return {
        "id": p.id,
        "provider": p.provider,
        "label": p.label,
        "base_url": p.base_url,
        "default_model": p.default_model,
        "is_default": p.is_default,
        "api_key_masked": masked,
    }


@router.get("/workspaces/{ws}/llm-providers")
def list_providers(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(LlmProvider).where(LlmProvider.workspace_id == ws).order_by(LlmProvider.label)
    )
    return [_provider(p) for p in rows]


class ProviderIn(BaseModel):
    provider: Literal["openai", "anthropic", "google", "openai-compatible"]
    label: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=4, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str = Field(min_length=1, max_length=100)
    is_default: bool = False


@router.post("/workspaces/{ws}/llm-providers")
def add_provider(ws: str, body: ProviderIn, ctx: SecretManagers) -> dict[str, Any]:
    if body.provider not in PROVIDERS:
        raise AppError(422, "지원하지 않는 AI 공급자예요.", "목록에서 공급자를 고르세요.")
    if body.provider == "openai-compatible" and not body.base_url:
        raise AppError(
            422, "호환 API는 주소(base URL)가 필요해요.", "예: https://api.example.com/v1"
        )
    existing = list(ctx.db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == ws)))
    is_default = body.is_default or not existing
    if is_default:
        for p in existing:
            p.is_default = False
    row = LlmProvider(
        workspace_id=ws,
        provider=body.provider,
        label=body.label,
        api_key_encrypted=encrypt_str(body.api_key.strip()),
        base_url=body.base_url or None,
        default_model=body.default_model.strip(),
        is_default=is_default,
    )
    ctx.db.add(row)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_provider.create",
        target_type="llm_provider",
        target_id=row.id,
        meta={"provider": body.provider, "label": body.label, "api_key": mask(body.api_key)},
    )
    ctx.db.commit()
    return _provider(row)


@router.delete("/workspaces/{ws}/llm-providers/{provider_id}", status_code=204)
def delete_provider(ws: str, provider_id: str, ctx: SecretManagers) -> Response:
    row = ctx.db.get(LlmProvider, provider_id)
    if row is None or row.workspace_id != ws:
        raise not_found("AI 연결")
    was_default = row.is_default
    ctx.db.delete(row)
    ctx.db.flush()
    if was_default:
        other = ctx.db.scalar(select(LlmProvider).where(LlmProvider.workspace_id == ws).limit(1))
        if other:
            other.is_default = True
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="llm_provider.delete",
        target_type="llm_provider",
        target_id=provider_id,
    )
    ctx.db.commit()
    return Response(status_code=204)


# ---------------- 노드·템플릿·프롬프트 ----------------
@router.get("/workspaces/{ws}/nodes")
def list_nodes(ws: str, ctx: Members) -> list[dict[str, Any]]:
    market.ensure_market_nodes(ctx.db)
    allowed = market.market_node_types(ctx.db, ws)
    return [s.describe() for s in registry.all() if s.source == "builtin" or s.type in allowed]


@router.get("/schemas/graph")
def graph_schema() -> dict[str, Any]:
    return Graph.model_json_schema(by_alias=True)


@router.get("/workspaces/{ws}/templates")
def list_templates(ws: str, ctx: Members) -> list[dict[str, Any]]:
    return market.templates(ctx.db, ws)


@router.get("/workspaces/{ws}/prompt-packs")
def list_prompt_packs(ws: str, ctx: Members) -> list[dict[str, Any]]:
    return market.prompt_packs(ctx.db, ws)


# ---------------- 운영 ----------------
def run_dict(r: Run) -> dict[str, Any]:
    return {
        "id": r.id,
        "app_id": r.app_id,
        "version_id": r.version_id,
        "trigger": r.trigger,
        "status": r.status,
        "input": r.input,
        "output": r.output,
        "error": r.error,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "created_at": r.created_at,
        "token_usage": r.token_usage or {},
        "cost": float(r.cost or 0),
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AppError(
            422, "날짜 형식이 올바르지 않아요.", "YYYY-MM-DD 형식으로 입력하세요."
        ) from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.get("/workspaces/{ws}/runs")
def list_runs(
    ws: str,
    ctx: Viewers,
    app: str | None = None,
    status: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
) -> list[dict[str, Any]]:
    q = select(Run, App.name).join(App, App.id == Run.app_id).where(App.workspace_id == ws)
    hidden = hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    if hidden:
        q = q.where(or_(App.project_id.is_(None), App.project_id.not_in(hidden)))
    if app:
        q = q.where(Run.app_id == app)
    if status:
        q = q.where(Run.status == status)
    start, end = _parse_dt(from_), _parse_dt(to)
    if start:
        q = q.where(Run.created_at >= start)
    if end:
        q = q.where(Run.created_at <= end)
    rows = ctx.db.execute(q.order_by(Run.created_at.desc()).limit(200)).all()
    return [{**run_dict(r), "app_name": name} for r, name in rows]


@router.get("/workspaces/{ws}/usage")
def usage(
    ws: str,
    ctx: Viewers,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
) -> dict[str, Any]:
    q = select(Run, App.name).join(App, App.id == Run.app_id).where(App.workspace_id == ws)
    start, end = _parse_dt(from_), _parse_dt(to)
    if start:
        q = q.where(Run.created_at >= start)
    if end:
        q = q.where(Run.created_at <= end)
    by_app: dict[str, dict[str, Any]] = {}
    total_in = total_out = 0
    total_cost = Decimal("0")
    total_runs = 0
    for r, name in ctx.db.execute(q).all():
        u = r.token_usage or {}
        i, o = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
        c = Decimal(str(r.cost or 0))
        entry = by_app.setdefault(
            r.app_id,
            {
                "app_id": r.app_id,
                "app_name": name,
                "runs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": Decimal("0"),
            },
        )
        entry["runs"] += 1
        entry["input_tokens"] += i
        entry["output_tokens"] += o
        entry["cost"] += c
        total_runs += 1
        total_in += i
        total_out += o
        total_cost += c
    apps = sorted(by_app.values(), key=lambda x: x["cost"], reverse=True)
    for a in apps:
        a["cost"] = float(a["cost"])
    return {
        "total_runs": total_runs,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost": float(total_cost),
        "by_app": apps,
    }


@router.get("/workspaces/{ws}/audit-logs")
def audit_logs(ws: str, ctx: Managers) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.workspace_id == ws)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
    ).all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "user_email": email,
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "meta": a.meta,
            "created_at": a.created_at,
        }
        for a, email in rows
    ]
