"""마켓: 목록·상세, 설치(mock 결제)·제거, 설치 목록."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import or_, select

from api.core.errors import not_found
from api.deps import (
    ANY_MEMBER,
    MANAGE_MARKET,
    Ctx,
    CurrentUser,
    DbDep,
    membership_role,
    require_role,
)
from api.market import service as svc
from api.models import Installation, MarketItem

router = APIRouter(tags=["market"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
MarketManagers = Annotated[Ctx, Depends(require_role(MANAGE_MARKET))]


def _item(m: MarketItem, installed: set[str] | None, detail: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": m.key,
        "type": m.type,
        "name": m.name,
        "summary": m.summary,
        "version": m.version,
        "publisher": m.publisher,
        "price": m.price,
        "tags": m.tags or [],
        "installs": m.installs,
        "installed": (m.key in installed) if installed is not None else None,
        "category": svc.category_of(m),
    }
    if detail:
        out["description_md"] = m.description_md
        out["manifest"] = m.manifest
        if m.type == "template":
            out["preview"] = svc.template_preview(m)
    return out


def _installed_for(db: Any, user_id: str, workspace_id: str | None) -> set[str] | None:
    if not workspace_id or membership_role(db, user_id, workspace_id) is None:
        return None
    return svc.installed_keys(db, workspace_id)


@router.get("/market/items")
def list_items(
    user: CurrentUser,
    db: DbDep,
    type: str | None = None,
    q: str | None = None,
    workspace_id: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    query = select(MarketItem).order_by(MarketItem.type, MarketItem.name)
    if type:
        query = query.where(MarketItem.type == type)
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                MarketItem.name.ilike(like),
                MarketItem.summary.ilike(like),
                MarketItem.key.ilike(like),
            )
        )
    installed = _installed_for(db, user.id, workspace_id)
    out = [_item(m, installed) for m in db.scalars(query)]
    if category:
        out = [i for i in out if i["category"] == category]
    return out


@router.get("/market/items/{key}")
def get_item(
    key: str, user: CurrentUser, db: DbDep, workspace_id: str | None = None
) -> dict[str, Any]:
    m = db.scalar(select(MarketItem).where(MarketItem.key == key))
    if m is None:
        raise not_found("마켓 아이템")
    return _item(m, _installed_for(db, user.id, workspace_id), detail=True)


class InstallIn(BaseModel):
    item_key: str


def _installation(inst: Installation, item: MarketItem | None) -> dict[str, Any]:
    latest = item.version if item else inst.version
    return {
        "id": inst.id,
        "item_key": item.key if item else "",
        "item_name": item.name if item else "",
        "type": item.type if item else "",
        "version": inst.version,
        "latest_version": latest,
        "update_available": _newer(latest, inst.version),
        "status": inst.status,
        "installed_at": inst.installed_at,
    }


def _ver(v: str) -> tuple[int, ...]:
    out = []
    for part in str(v).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _newer(latest: str, current: str) -> bool:
    return _ver(latest) > _ver(current)


@router.post("/workspaces/{ws}/market/install")
def install(ws: str, body: InstallIn, ctx: MarketManagers) -> dict[str, Any]:
    inst = svc.install(ctx.db, ws, body.item_key, ctx.user.id)
    return _installation(inst, ctx.db.get(MarketItem, inst.item_id))


@router.get("/workspaces/{ws}/market/installations")
def installations(ws: str, ctx: Members) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(Installation, MarketItem)
        .join(MarketItem, MarketItem.id == Installation.item_id)
        .where(Installation.workspace_id == ws, Installation.status == "installed")
        .order_by(Installation.installed_at.desc())
    ).all()
    return [_installation(i, m) for i, m in rows]


@router.delete("/workspaces/{ws}/market/installations/{installation_id}", status_code=204)
def uninstall(ws: str, installation_id: str, ctx: MarketManagers) -> Response:
    svc.uninstall(ctx.db, ws, installation_id, ctx.user.id)
    return Response(status_code=204)


@router.post("/workspaces/{ws}/market/installations/{installation_id}/update")
def update_installation(ws: str, installation_id: str, ctx: MarketManagers) -> dict[str, Any]:
    inst = svc.update_installation(ctx.db, ws, installation_id, ctx.user.id)
    return _installation(inst, ctx.db.get(MarketItem, inst.item_id))
