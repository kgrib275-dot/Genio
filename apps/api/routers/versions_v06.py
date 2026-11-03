"""v0.6 버전 비교(ADR 0010): 두 버전, 또는 버전과 지금 작업본의 차이."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from api.core.errors import AppError
from api.deps import VIEW_RUNS, Ctx, require_role
from api.models import WorkflowVersion
from api.services import apps as svc
from api.services.graph_diff import diff_graphs

router = APIRouter(tags=["versions-v06"])
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]


def _graph_of(ctx: Ctx, app_id: str, ref: str) -> tuple[dict[str, Any], str]:
    if ref == "draft":
        app = svc.get_app(ctx.db, app_id)
        return dict(app.draft_graph or {}), "작업본"
    try:
        number = int(ref)
    except ValueError:
        raise AppError(
            422, "비교할 버전을 알아보지 못했어요.", "버전 번호나 'draft'(작업본)를 고르세요."
        ) from None
    v = ctx.db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.app_id == app_id, WorkflowVersion.version == number
        )
    )
    if v is None:
        raise AppError(
            404, f"버전 {number}을(를) 찾지 못했어요.", "버전 목록을 새로고침해 다시 고르세요."
        )
    return dict(v.graph or {}), f"버전 {number}"


@router.get("/apps/{app_id}/version-diff")
def version_diff(
    app_id: str,
    ctx: AppViewers,
    base: Annotated[str, Query(alias="from", max_length=20)],
    target: Annotated[str, Query(alias="to", max_length=20)] = "draft",
) -> dict[str, Any]:
    old, old_name = _graph_of(ctx, app_id, base)
    new, new_name = _graph_of(ctx, app_id, target)
    return {"from": old_name, "to": new_name, **diff_graphs(old, new)}
