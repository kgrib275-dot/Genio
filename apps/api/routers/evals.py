"""평가 세트: 질문·조건 저장, 한 번에 돌리기, 채점 결과와 점수 변화."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.engine.executor import _limits_message
from api.services import apps as app_svc
from api.services import evals as svc

router = APIRouter(tags=["evals"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]


class CaseIn(BaseModel):
    id: str = Field(default="", max_length=36)
    name: str = Field(default="", max_length=100)
    input: dict[str, Any] = Field(default_factory=dict)
    contains: list[str] = Field(default_factory=list, max_length=svc.MAX_TERMS)
    not_contains: list[str] = Field(default_factory=list, max_length=svc.MAX_TERMS)
    max_seconds: float | None = Field(default=None, ge=0, le=600)
    json_valid: bool = False


class CasesIn(BaseModel):
    cases: list[CaseIn] = Field(default_factory=list, max_length=svc.MAX_CASES)


@router.get("/apps/{app_id}/evals/cases")
def get_cases(app_id: str, ctx: AppViewers) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    return {"cases": svc.get_cases(app), "max_cases": svc.MAX_CASES}


@router.put("/apps/{app_id}/evals/cases")
def put_cases(app_id: str, body: CasesIn, ctx: AppBuilders) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    cleaned = svc.save_cases(ctx.db, app, [c.model_dump() for c in body.cases])
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.eval_cases",
        target_type="app",
        target_id=app.id,
        meta={"count": len(cleaned)},
    )
    ctx.db.commit()
    return {"cases": cleaned, "max_cases": svc.MAX_CASES}


@router.post("/apps/{app_id}/evals", status_code=201)
def run_eval(app_id: str, ctx: AppBuilders) -> dict[str, Any]:
    """지금 작업본으로 평가 세트를 한 번에 돌린다(결과는 목록·묶음 번호로 확인)."""
    app = app_svc.get_app(ctx.db, app_id)
    blocked = _limits_message(ctx.db, app)
    if blocked:
        raise AppError(429, blocked, "관리 > 사용량에서 한도를 확인하세요.")
    graph = app.draft_graph or {}
    result = app_svc.validate_for_app(ctx.db, app, graph)
    if not result.valid:
        raise AppError(
            422,
            "흐름에 고칠 부분이 있어 평가를 돌리지 못했어요.",
            "빨간 테두리 단계의 오류를 먼저 고치세요.",
            errors=[e.model_dump() for e in result.errors],
        )
    out = svc.start(ctx.db, app, ctx.user.id, dict(graph))
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.eval_run",
        target_type="app",
        target_id=app.id,
        meta={"batch": out["batch"], "total": out["total"]},
    )
    ctx.db.commit()
    return out


@router.get("/apps/{app_id}/evals")
def list_evals(app_id: str, ctx: AppViewers) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    return {"batches": svc.history(ctx.db, app)}


@router.get("/apps/{app_id}/evals/{batch}")
def get_eval(app_id: str, batch: str, ctx: AppViewers) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    return svc.report(ctx.db, app, batch)
