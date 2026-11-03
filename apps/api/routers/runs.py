"""실행 상세, 실행 로그 SSE, 승인."""

import contextlib
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.audit import audit
from api.core.errors import AppError, forbidden, not_found
from api.db import SessionLocal
from api.deps import VIEW_RUNS, Ctx, require_role
from api.engine import events
from api.engine.executor import load_graph
from api.models import App, Run, RunStep
from api.routers.common import sse_frame, sse_response
from api.routers.workspaces import run_dict
from api.services.queue import enqueue_run
from nodes import NodeError

router = APIRouter(tags=["runs"])
RunViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="run"))]
STREAM_MAX_SECONDS = 15 * 60
END_STATES = {"succeeded", "failed", "waiting_approval"}


def step_dict(s: RunStep) -> dict[str, Any]:
    return {
        "id": s.id,
        "node_id": s.node_id,
        "status": s.status,
        "input": s.input,
        "output": s.output,
        "logs": s.logs,
        "started_at": s.started_at,
        "finished_at": s.finished_at,
    }


def _steps(db: Session, run_id: str) -> list[RunStep]:
    return list(
        db.scalars(
            select(RunStep)
            .where(RunStep.run_id == run_id)
            .order_by(RunStep.seq, RunStep.started_at)
        )
    )


def run_detail(db: Session, run: Run) -> dict[str, Any]:
    try:
        graph = load_graph(db, run).dump()
    except NodeError:
        graph = {"version": 1, "nodes": [], "edges": [], "variables": {}}
    return {
        **run_dict(run),
        "steps": [step_dict(s) for s in _steps(db, run.id)],
        "approval": run.approval,
        "graph": graph,
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, ctx: RunViewers) -> dict[str, Any]:
    run = ctx.db.get(Run, run_id)
    if run is None:
        raise not_found("실행 기록")
    return run_detail(ctx.db, run)


def _stream(run_id: str) -> Iterator[str]:
    sub = events.subscriber(run_id)
    seen_steps: dict[str, tuple[str, Any]] = {}
    last_status = None
    started = time.time()
    try:
        while time.time() - started < STREAM_MAX_SECONDS:
            with SessionLocal() as db:
                run = db.get(Run, run_id)
                if run is None:
                    yield sse_frame(
                        "error",
                        {"message": "실행 기록을 찾을 수 없어요.", "hint": "목록에서 다시 여세요."},
                    )
                    return
                rd = run_dict(run)
                if run.status != last_status:
                    last_status = run.status
                    yield sse_frame("run", rd)
                for s in _steps(db, run_id):
                    sig = (s.status, s.finished_at)
                    if seen_steps.get(s.id) != sig:
                        seen_steps[s.id] = sig
                        yield sse_frame("step", step_dict(s))
                if run.status in END_STATES:
                    yield sse_frame("end", rd)
                    return
            if sub is not None:
                sub.get_message(timeout=1.0)
            else:
                time.sleep(0.4)
            yield ": keep-alive\n\n"
    finally:
        if sub is not None:
            with contextlib.suppress(Exception):
                sub.close()


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, ctx: RunViewers) -> StreamingResponse:
    del ctx
    return sse_response(_stream(run_id))


class ApproveIn(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=1000)


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, body: ApproveIn, ctx: RunViewers) -> dict[str, Any]:
    run = ctx.db.get(Run, run_id)
    if run is None:
        raise not_found("실행 기록")
    if run.status != "waiting_approval" or not run.approval:
        raise AppError(
            409, "승인을 기다리는 실행이 아니에요.", "실행 상태를 새로고침해 확인하세요."
        )
    if "approved" in run.approval:
        raise AppError(409, "이미 결정된 승인 요청이에요.", "실행 결과를 확인하세요.")
    roles = run.approval.get("approver_roles") or []
    if roles and ctx.role not in roles and ctx.role != "owner":
        raise forbidden()
    run.approval = {
        **run.approval,
        "approved": body.approved,
        "comment": body.comment,
        "decided_by": ctx.user.id,
        "decided_by_name": ctx.user.name,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    app = ctx.db.get(App, run.app_id)
    audit(
        ctx.db,
        workspace_id=app.workspace_id if app else None,
        user_id=ctx.user.id,
        action="run.approve" if body.approved else "run.reject",
        target_type="run",
        target_id=run.id,
        meta={"comment": body.comment},
    )
    ctx.db.commit()
    enqueue_run(run.id)
    ctx.db.expire_all()
    fresh = ctx.db.get(Run, run_id)
    if fresh is None:
        raise not_found("실행 기록")
    return run_detail(ctx.db, fresh)
