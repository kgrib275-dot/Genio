"""워크스페이스: 멤버·초대·역할, AI 연결(LLM 키), 단계 카탈로그, 템플릿, 운영(실행 이력·사용량·감사 로그)."""

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select

from api.connectors.http_auth import auth_headers
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
    CurrentUser,
    Role,
    require_role,
)
from api.engine import pricing, safe_http
from api.llm.base import LlmError
from api.llm.catalog import catalog
from api.llm.openai_adapter import azure_endpoint
from api.llm.presets import PRESETS, is_rerank, provider_list
from api.llm.registry import PROVIDERS
from api.market import service as market
from api.models import (
    App,
    AuditLog,
    ConnectorCredential,
    Invitation,
    LlmProvider,
    Membership,
    Run,
    User,
    Workspace,
)
from api.routers.common import public_origin
from api.schemas.graph import Graph
from api.services import limits
from api.services.llm_keys import provider_view
from api.services.projects import hidden_project_ids
from nodes import NodeError, registry

router = APIRouter(tags=["workspaces"])

Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
Viewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS))]


# ---------------- 멤버·초대 ----------------
def _member(m: Membership, u: User, only_here: bool | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": m.id,
        "user_id": u.id,
        "email": u.email,
        "name": u.name,
        "role": m.role,
        # v0.7: 2단계 인증을 켰는지(관리자가 휴대폰 분실 시 끌 수 있게)
        "two_factor": bool(u.totp_enabled),
    }
    if only_here is not None:
        out["only_here"] = only_here
    return out


@router.get("/workspaces/{ws}/members")
def list_members(ws: str, ctx: Members) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == ws)
    ).all()
    # 이 워크스페이스에만 속한 계정인지(관리자가 비밀번호를 재설정할 수 있는지)
    shared = set(
        ctx.db.scalars(
            select(Membership.user_id).where(
                Membership.user_id.in_([u.id for _, u in rows]), Membership.workspace_id != ws
            )
        )
    )
    order = {"owner": 0, "admin": 1, "builder": 2, "operator": 3, "member": 4}
    return sorted(
        (_member(m, u, u.id not in shared) for m, u in rows),
        key=lambda x: (order.get(x["role"], 9), x["email"]),
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
    # 키 목록·돌려쓰기 방식·재정렬 전용 여부까지 담은 화면용 모양(키 원문은 없다)
    return provider_view(p)


@router.get("/workspaces/{ws}/llm-providers")
def list_providers(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(LlmProvider).where(LlmProvider.workspace_id == ws).order_by(LlmProvider.label)
    )
    return [_provider(p) for p in rows]


class ProviderIn(BaseModel):
    # v0.6: 기본 5종 + OpenAI 호환 preset(GET /llm/providers)
    provider: str = Field(min_length=2, max_length=30)
    label: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=4, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str = Field(min_length=1, max_length=100)
    is_default: bool = False


@router.post("/workspaces/{ws}/llm-providers")
def add_provider(ws: str, body: ProviderIn, ctx: SecretManagers) -> dict[str, Any]:
    if body.provider not in PROVIDERS:
        raise AppError(422, "지원하지 않는 AI 공급자예요.", "목록에서 공급자를 고르세요.")
    if body.base_url and not body.base_url.strip().lower().startswith(("https://", "http://")):
        raise AppError(
            422, "주소(base URL) 형식이 올바르지 않아요.", "https://로 시작하는 주소를 넣으세요."
        )
    if body.provider == "openai-compatible" and not body.base_url:
        raise AppError(
            422, "호환 API는 주소(base URL)가 필요해요.", "예: https://api.example.com/v1"
        )
    if body.provider == "rerank-compatible" and not body.base_url:
        raise AppError(
            422,
            "재정렬 호환 서버는 주소가 필요해요.",
            "예: http://서버:8000 (끝에 /rerank가 없으면 붙여서 불러요)",
        )
    if body.provider == "azure":
        if not body.base_url:
            raise AppError(
                422,
                "Azure는 리소스 주소가 필요해요.",
                "예: https://my-resource.openai.azure.com/ (모델 칸에는 배포 이름)",
            )
        try:
            azure_endpoint(body.base_url)
        except LlmError as exc:
            raise AppError(422, exc.message, exc.hint) from None
    existing = list(ctx.db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == ws)))
    # 재정렬 전용 연결은 '기본 연결'이 될 수 없고, 기본 연결 정하기에도 끼지 않는다
    chat_rows = [p for p in existing if not is_rerank(p.provider)]
    is_default = (body.is_default or not chat_rows) and not is_rerank(body.provider)
    if is_default:
        for p in chat_rows:
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


class ProviderTestIn(BaseModel):
    provider: str = Field(min_length=2, max_length=30)
    api_key: str = Field(min_length=4, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    # 재정렬 전용 연결 시험에 쓸 모델 이름(비우면 공급자의 첫 모델)
    model: str | None = Field(default=None, max_length=100)


def probe_connection(
    provider: str, api_key: str, base_url: str | None, model: str | None = None
) -> dict[str, Any]:
    from api.llm import rerank
    from api.llm.probe import list_models

    if provider not in PROVIDERS:
        raise AppError(422, "지원하지 않는 AI 공급자예요.", "목록에서 공급자를 고르세요.")
    started = time.perf_counter()
    if is_rerank(provider):
        use = (model or "").strip() or PRESETS[provider].default_model
        if not use:
            return {
                "ok": False,
                "message": "재정렬 모델 이름이 없어요.",
                "hint": "기본 모델 칸에 서버의 재정렬 모델 이름을 적어 주세요.",
                "models": [],
            }
        err = rerank.probe(provider, api_key, base_url or None, use)
        if err is not None:
            return {"ok": False, "message": err.message, "hint": err.hint, "models": []}
        return {
            "ok": True,
            "message": "연결됐어요. 재정렬 모델이 답했어요.",
            "hint": "",
            "models": [],
            "ms": round((time.perf_counter() - started) * 1000),
        }
    try:
        models = list_models(provider, api_key, base_url or None)
    except LlmError as exc:
        return {"ok": False, "message": exc.message, "hint": exc.hint, "models": []}
    return {
        "ok": True,
        "message": f"연결됐어요. 쓸 수 있는 모델 {len(models)}개를 불러왔어요.",
        "hint": "",
        "models": models,
        "ms": round((time.perf_counter() - started) * 1000),
    }


@router.post("/workspaces/{ws}/llm-providers/test")
def test_new_provider(ws: str, body: ProviderTestIn, ctx: SecretManagers) -> dict[str, Any]:
    """저장하기 전에 키로 연결해 보고, 그 키로 쓸 수 있는 모델 목록을 돌려준다."""
    del ws, ctx
    return probe_connection(body.provider, body.api_key.strip(), body.base_url, body.model)


@router.post("/workspaces/{ws}/llm-providers/{provider_id}/test")
def test_saved_provider(ws: str, provider_id: str, ctx: Builders) -> dict[str, Any]:
    """저장된 연결을 시험한다(키는 서버에서만 풀어 쓴다)."""
    row = ctx.db.get(LlmProvider, provider_id)
    if row is None or row.workspace_id != ws:
        raise not_found("AI 연결")
    return probe_connection(
        row.provider, decrypt_str(row.api_key_encrypted), row.base_url, row.default_model
    )


@router.delete("/workspaces/{ws}/llm-providers/{provider_id}", status_code=204)
def delete_provider(ws: str, provider_id: str, ctx: SecretManagers) -> Response:
    row = ctx.db.get(LlmProvider, provider_id)
    if row is None or row.workspace_id != ws:
        raise not_found("AI 연결")
    was_default = row.is_default
    ctx.db.delete(row)
    ctx.db.flush()
    if was_default:
        other = next(
            (
                p
                for p in ctx.db.scalars(select(LlmProvider).where(LlmProvider.workspace_id == ws))
                if not is_rerank(p.provider)
            ),
            None,
        )
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


# ---------------- 단계·템플릿·프롬프트 ----------------
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
    limit: int = Query(default=200, ge=1, le=1000),
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
    rows = ctx.db.execute(q.order_by(Run.created_at.desc()).limit(limit)).all()
    return [{**run_dict(r), "app_name": name} for r, name in rows]


@router.get("/workspaces/{ws}/usage")
def usage(
    ws: str,
    ctx: Viewers,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
    group: Literal["app", "user"] = "app",
) -> dict[str, Any]:
    if group == "user":
        return _usage_by_user(ctx, ws, _parse_dt(from_), _parse_dt(to))
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
def audit_logs(
    ws: str, ctx: Managers, limit: int = Query(default=200, ge=1, le=1000)
) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.workspace_id == ws)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
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


# ---------------- v0.5: 사람별 비용·예상 비용·모델 카탈로그(S8, §6) ----------------
def _usage_by_user(
    ctx: Ctx, ws: str, start: datetime | None, end: datetime | None
) -> dict[str, Any]:
    q = (
        select(Run, User)
        .join(App, App.id == Run.app_id)
        .outerjoin(User, User.id == Run.created_by)
        .where(App.workspace_id == ws)
    )
    if start:
        q = q.where(Run.created_at >= start)
    if end:
        q = q.where(Run.created_at <= end)
    by_user: dict[str, dict[str, Any]] = {}
    totals: dict[str, Any] = {
        "runs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": Decimal("0"),
    }
    for r, u in ctx.db.execute(q).all():
        key = u.id if u else "_anon"
        entry = by_user.setdefault(
            key,
            {
                "user_id": u.id if u else None,
                "name": u.name if u else "방문자·자동 실행",
                "email": u.email if u else None,
                "runs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": Decimal("0"),
            },
        )
        usage_ = r.token_usage or {}
        i, o = int(usage_.get("input_tokens", 0)), int(usage_.get("output_tokens", 0))
        c = Decimal(str(r.cost or 0))
        for d in (entry, totals):
            d["runs"] += 1
            d["input_tokens"] += i
            d["output_tokens"] += o
            d["cost"] += c
    users = sorted(by_user.values(), key=lambda x: x["cost"], reverse=True)
    for e in users:
        e["cost"] = float(e["cost"])
    return {
        "total_runs": totals["runs"],
        "total_input_tokens": totals["input_tokens"],
        "total_output_tokens": totals["output_tokens"],
        "total_cost": float(totals["cost"]),
        "by_user": users,
    }


@router.get("/workspaces/{ws}/usage/estimate")
def usage_estimate(
    ws: str,
    ctx: Viewers,
    model: Annotated[str, Query(min_length=1, max_length=100)],
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict[str, Any]:
    """최근 N일 토큰을 다른 모델로 썼다면 얼마였을지(S8 모델 교체 비용 비교)."""
    price = pricing.PRICES.get(model)
    if price is None:
        raise AppError(
            422,
            "단가를 모르는 모델이에요.",
            "모델 목록(카탈로그)에 있는 모델을 고르세요.",
        )
    since = datetime.now(UTC) - timedelta(days=days)
    rows = ctx.db.scalars(
        select(Run)
        .join(App, App.id == Run.app_id)
        .where(App.workspace_id == ws, Run.created_at >= since)
    )
    tin = tout = 0
    current = Decimal("0")
    for r in rows:
        u = r.token_usage or {}
        tin += int(u.get("input_tokens", 0))
        tout += int(u.get("output_tokens", 0))
        current += Decimal(str(r.cost or 0))
    estimated = pricing.cost_of(model, tin, tout)
    return {
        "model": model,
        "days": days,
        "input_tokens": tin,
        "output_tokens": tout,
        "current_cost": float(current),
        "estimated_cost": float(estimated),
        "difference": float(estimated - current),
        "price": {"input": float(Decimal(price[0])), "output": float(Decimal(price[1]))},
    }


@router.get("/llm/providers")
def llm_providers(user: CurrentUser) -> list[dict[str, Any]]:
    """AI 공급자 목록(v0.6): 기본 5종 + 키만 넣으면 되는 OpenAI 호환 공급자. 화면 묶음·기본 주소·모델."""
    del user
    return provider_list()


@router.get("/llm/catalog")
def llm_catalog(user: CurrentUser) -> list[dict[str, Any]]:
    """모델 카탈로그: 공급자·컨텍스트·단가(USD/100만 토큰)·도구 호출·이미지·임베딩."""
    del user
    return catalog()


# ---------------- v0.5: HTTP 시험 호출(§4 범용 HTTP 응답 미리보기) ----------------
class HttpPreviewIn(BaseModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str = Field(min_length=8, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    auth: dict[str, Any] | None = None


PREVIEW_BODY_CHARS = 8000


@router.post("/workspaces/{ws}/http/preview")
def http_preview(ws: str, body: HttpPreviewIn, ctx: Builders) -> dict[str, Any]:
    """HTTP 단계를 저장하기 전에 한 번 불러 보고 응답을 본다(사설망 차단 규칙 그대로)."""
    started = time.perf_counter()
    try:
        headers = {str(k)[:100]: str(v)[:2000] for k, v in list(body.headers.items())[:30]}
        headers.update(auth_headers(ctx.db, ws, body.auth))
        res = safe_http.request(body.method, body.url, headers=headers, body=body.body)
    except NodeError as exc:
        raise AppError(422, exc.message, "주소·인증·값을 확인한 뒤 다시 시험 호출하세요.") from None
    out_body = res.get("body")
    text = out_body if isinstance(out_body, str) else json.dumps(out_body, ensure_ascii=False)
    truncated = len(text) > PREVIEW_BODY_CHARS
    return {
        "status": res.get("status"),
        "headers": res.get("headers", {}),
        "body": (text[:PREVIEW_BODY_CHARS] if truncated else out_body),
        "truncated": truncated,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


# ---------------- v0.5: 한도·알림·보관 기간(P1) ----------------
class LimitsPatch(BaseModel):
    monthly_budget_usd: float | None = None
    cost_alert_usd: float | None = None
    alert_on_failure: bool | None = None
    alert_emails: list[str] | None = None
    alert_credential_id: str | None = None
    retention_days: int | None = None


def _limits_out(ctx: Ctx, w: Workspace) -> dict[str, Any]:
    return {
        **limits.get_limits(w),
        "month_cost": float(limits.month_cost(ctx.db, w.id)),
    }


@router.get("/workspaces/{ws}/limits")
def get_limits(ws: str, ctx: Managers) -> dict[str, Any]:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    return _limits_out(ctx, w)


@router.patch("/workspaces/{ws}/limits")
def patch_limits(ws: str, body: LimitsPatch, ctx: Managers) -> dict[str, Any]:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    patch = body.model_dump(exclude_unset=True)
    cred_id = patch.get("alert_credential_id")
    if cred_id:
        cred = ctx.db.get(ConnectorCredential, cred_id)
        if cred is None or cred.workspace_id != ws:
            raise AppError(
                422,
                "알림 메일에 쓸 연결 정보를 찾지 못했어요.",
                "Email (SMTP) 연결 정보를 고르세요.",
            )
    new = limits.clean_limits(patch, limits.get_limits(w))
    w.settings = {**(w.settings or {}), "limits": new}
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="workspace.limits",
        target_type="workspace",
        target_id=ws,
        meta={k: v for k, v in new.items() if k != "alert_emails"},
    )
    ctx.db.commit()
    return _limits_out(ctx, w)
