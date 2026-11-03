"""관리 콘솔(소유자·관리자 전용): 개요, 워크스페이스 설정, 멤버 내보내기·소유권 넘기기, 초대 취소, API 키 전체, 시스템 설정."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from api.core.audit import audit
from api.core.errors import AppError, forbidden, not_found
from api.deps import ANY_MEMBER, MANAGE_MEMBERS, Ctx, CurrentUser, DbDep, require_role
from api.models import (
    App,
    AppApiKey,
    Conversation,
    Document,
    Invitation,
    KnowledgeBase,
    LlmProvider,
    Membership,
    Run,
    Workspace,
)
from api.services import system

router = APIRouter(tags=["admin"])
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Owners = Annotated[Ctx, Depends(require_role(("owner",)))]


def _ws(w: Workspace) -> dict[str, Any]:
    return {"id": w.id, "name": w.name, "settings": w.settings or {}}


@router.get("/workspaces/{ws}")
def get_workspace(ws: str, ctx: Members) -> dict[str, Any]:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    return _ws(w)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    settings: dict[str, Any] | None = None


@router.patch("/workspaces/{ws}")
def update_workspace(ws: str, body: WorkspacePatch, ctx: Managers) -> dict[str, Any]:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    if body.name:
        w.name = body.name
    if body.settings is not None:
        cur = dict(w.settings or {})
        dm = body.settings.get("default_models")
        if isinstance(dm, dict):
            valid = set(
                ctx.db.scalars(select(LlmProvider.id).where(LlmProvider.workspace_id == ws))
            )
            clean = {
                k: v
                for k, v in dm.items()
                if k in ("chat", "embedding") and (v in valid or v in (None, ""))
            }
            cur["default_models"] = {**cur.get("default_models", {}), **clean}
        rl = body.settings.get("public_rate_limit_per_minute")
        if rl is not None:
            cur["public_rate_limit_per_minute"] = max(1, min(int(rl), 600))
        w.settings = cur
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="workspace.update",
        target_type="workspace",
        target_id=ws,
        meta={"name": w.name},
    )
    ctx.db.commit()
    return _ws(w)


@router.get("/workspaces/{ws}/admin/overview")
def overview(ws: str, ctx: Managers, days: int = Query(default=14, ge=1, le=90)) -> dict[str, Any]:
    db = ctx.db
    app_ids = list(db.scalars(select(App.id).where(App.workspace_id == ws)))
    counts = {
        "members": db.scalar(
            select(func.count()).select_from(Membership).where(Membership.workspace_id == ws)
        )
        or 0,
        "apps": len(app_ids),
        "published_apps": db.scalar(
            select(func.count())
            .select_from(App)
            .where(App.workspace_id == ws, App.status == "published")
        )
        or 0,
        "knowledge_bases": db.scalar(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.workspace_id == ws)
        )
        or 0,
        "documents": db.scalar(
            select(func.count())
            .select_from(Document)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(KnowledgeBase.workspace_id == ws)
        )
        or 0,
        "api_keys": db.scalar(
            select(func.count()).select_from(AppApiKey).where(AppApiKey.app_id.in_(app_ids))
        )
        or 0
        if app_ids
        else 0,
    }
    since = (datetime.now(UTC) - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    keys = [(since + timedelta(days=i)).date().isoformat() for i in range(days)]
    rows: dict[str, dict[str, Any]] = {
        k: {
            "date": k,
            "runs": 0,
            "tokens": 0,
            "cost": Decimal(0),
            "users": set(),
            "conversations": 0,
        }
        for k in keys
    }
    per_app: dict[str, dict[str, Any]] = defaultdict(lambda: {"runs": 0, "cost": Decimal(0)})
    names = {a.id: a.name for a in db.scalars(select(App).where(App.workspace_id == ws))}

    def day(dt: datetime) -> str:
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).date().isoformat()

    if app_ids:
        for r in db.scalars(select(Run).where(Run.app_id.in_(app_ids), Run.created_at >= since)):
            d = rows.get(day(r.created_at))
            if d is None:
                continue
            u = r.token_usage or {}
            d["runs"] += 1
            d["tokens"] += int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))
            d["cost"] += Decimal(str(r.cost or 0))
            if r.created_by:
                d["users"].add(r.created_by)
            per_app[r.app_id]["runs"] += 1
            per_app[r.app_id]["cost"] += Decimal(str(r.cost or 0))
        for c in db.scalars(
            select(Conversation).where(
                Conversation.app_id.in_(app_ids), Conversation.created_at >= since
            )
        ):
            d = rows.get(day(c.created_at))
            if d is not None:
                d["conversations"] += 1
                if c.user_id:
                    d["users"].add(c.user_id)
    out_days = [
        {
            "date": d["date"],
            "runs": d["runs"],
            "tokens": d["tokens"],
            "cost": float(d["cost"]),
            "active_users": len(d["users"]),
            "conversations": d["conversations"],
        }
        for d in (rows[k] for k in keys)
    ]
    top = sorted(
        (
            {"app_id": a, "app_name": names.get(a, ""), "runs": v["runs"], "cost": float(v["cost"])}
            for a, v in per_app.items()
        ),
        key=lambda x: x["runs"],
        reverse=True,
    )[:5]
    return {"counts": counts, "days": out_days, "top_apps": top}


@router.delete("/workspaces/{ws}/members/{member_id}", status_code=204)
def remove_member(ws: str, member_id: str, ctx: Managers) -> Response:
    m = ctx.db.get(Membership, member_id)
    if m is None or m.workspace_id != ws:
        raise not_found("멤버")
    if m.user_id == ctx.user.id:
        raise AppError(409, "자기 자신은 내보낼 수 없어요.", "다른 관리자에게 요청하세요.")
    if m.role == "owner":
        raise AppError(409, "소유자는 내보낼 수 없어요.", "먼저 소유권을 다른 멤버에게 넘기세요.")
    if m.role == "admin" and ctx.role != "owner":
        raise AppError(
            403, "관리자는 소유자만 내보낼 수 있어요.", "워크스페이스 소유자에게 요청하세요."
        )
    ctx.db.delete(m)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="member.remove",
        target_type="membership",
        target_id=member_id,
        meta={"user_id": m.user_id},
    )
    ctx.db.commit()
    return Response(status_code=204)


class TransferIn(BaseModel):
    member_id: str


@router.post("/workspaces/{ws}/transfer-ownership")
def transfer_ownership(ws: str, body: TransferIn, ctx: Owners) -> dict[str, bool]:
    target = ctx.db.get(Membership, body.member_id)
    if target is None or target.workspace_id != ws:
        raise not_found("멤버")
    if target.user_id == ctx.user.id:
        raise AppError(409, "이미 소유자예요.", "다른 멤버를 고르세요.")
    me = ctx.db.scalar(
        select(Membership).where(Membership.workspace_id == ws, Membership.user_id == ctx.user.id)
    )
    if me is None:
        raise forbidden()
    target.role = "owner"
    me.role = "admin"
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="workspace.transfer_ownership",
        target_type="membership",
        target_id=target.id,
    )
    ctx.db.commit()
    return {"ok": True}


@router.delete("/workspaces/{ws}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(ws: str, invitation_id: str, ctx: Managers) -> Response:
    inv = ctx.db.get(Invitation, invitation_id)
    if inv is None or inv.workspace_id != ws:
        raise not_found("초대")
    ctx.db.delete(inv)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="member.invite_revoke",
        target_type="invitation",
        target_id=inv.email,
    )
    ctx.db.commit()
    return Response(status_code=204)


@router.get("/workspaces/{ws}/admin/api-keys")
def all_api_keys(ws: str, ctx: Managers) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(AppApiKey, App.name)
        .join(App, App.id == AppApiKey.app_id)
        .where(App.workspace_id == ws)
        .order_by(AppApiKey.created_at.desc())
    ).all()
    return [
        {
            "id": k.id,
            "app_id": k.app_id,
            "app_name": name,
            "name": k.name,
            "prefix": k.prefix,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
        }
        for k, name in rows
    ]


# ---------------- 시스템 설정 ----------------
@router.get("/admin/system")
def get_system(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    return {"is_instance_admin": system.is_instance_admin(db, user.id), **system.get_system(db)}


class SystemPatch(BaseModel):
    allow_signup: bool | None = None
    show_demo_accounts: bool | None = None


@router.patch("/admin/system")
def patch_system(body: SystemPatch, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    if not system.is_instance_admin(db, user.id):
        raise AppError(
            403,
            "시스템 설정은 인스턴스 관리자만 바꿀 수 있어요.",
            "가장 먼저 만든 워크스페이스의 소유자에게 요청하세요.",
        )
    out = system.set_system(db, body.model_dump(exclude_none=True))
    audit(
        db,
        workspace_id=system.instance_workspace_id(db),
        user_id=user.id,
        action="system.update",
        target_type="system",
        meta=body.model_dump(exclude_none=True),
    )
    db.commit()
    return {"is_instance_admin": True, **out}
