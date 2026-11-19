"""앱 소유자 인수인계(멤버 관리 권한: owner·admin)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.deps import MANAGE_MEMBERS, Ctx, require_role
from api.services import ownership as svc

router = APIRouter(tags=["workspaces"])
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]


class TransferIn(BaseModel):
    to_user_id: str = Field(min_length=1, max_length=64)


@router.get("/workspaces/{ws}/members/{user_id}/assets")
def member_assets(ws: str, user_id: str, ctx: Managers) -> dict[str, Any]:
    return svc.summary(ctx.db, ws, user_id)


@router.post("/workspaces/{ws}/members/{user_id}/transfer")
def transfer_assets(ws: str, user_id: str, body: TransferIn, ctx: Managers) -> dict[str, int]:
    moved = svc.transfer(ctx.db, ws, user_id, body.to_user_id)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="member.transfer_assets",
        target_type="user",
        target_id=user_id,
        meta={"to": body.to_user_id, **moved},
    )
    ctx.db.commit()
    return moved
