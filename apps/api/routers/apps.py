"""앱·작업본·버전·검증·테스트 실행."""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select

from api.builder import metrics as builder_metrics
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import App, Run, WorkflowVersion
from api.routers.projects import check_project_target
from api.routers.workspaces import run_dict
from api.schemas.graph import Graph
from api.services import apps as svc
from api.services.projects import hidden_project_ids
from api.services.queue import enqueue_run

router = APIRouter(tags=["apps"])

WsMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]

AppType = Literal["chat", "workflow", "form"]


@router.get("/workspaces/{ws}/apps")
def list_apps(ws: str, ctx: WsMembers, project: str | None = None) -> list[dict[str, Any]]:
    q = select(App).where(App.workspace_id == ws).order_by(App.updated_at.desc())
    if ctx.role == "member":
        q = q.where(App.status == "published")
    if project == "none":
        q = q.where(App.project_id.is_(None))
    elif project:
        q = q.where(App.project_id == project)
    hidden = hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    if hidden:
        q = q.where(or_(App.project_id.is_(None), App.project_id.not_in(hidden)))
    apps = list(ctx.db.scalars(q))
    latest = svc.latest_versions(ctx.db, [a.id for a in apps])
    return [svc.app_dict(a, latest.get(a.id)) for a in apps]


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: AppType = "workflow"
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="🤖", max_length=40)
    template_key: str | None = None
    project_id: str | None = None


@router.post("/workspaces/{ws}/apps", status_code=201)
def create_app(ws: str, body: AppIn, ctx: WsBuilders) -> dict[str, Any]:
    check_project_target(ctx, ws, body.project_id)
    app = svc.create_app(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        name=body.name,
        app_type=body.type,
        description=body.description,
        icon=body.icon,
        template_key=body.template_key,
        project_id=body.project_id,
    )
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="app.create",
        target_type="app",
        target_id=app.id,
        meta={"name": app.name, "template": body.template_key},
    )
    ctx.db.commit()
    return svc.app_detail(ctx.db, app)


@router.get("/apps/{app_id}")
def get_app(app_id: str, ctx: AppViewers) -> dict[str, Any]:
    return svc.app_detail(ctx.db, svc.get_app(ctx.db, app_id))


class AppPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=40)
    type: AppType | None = None
    # 빈 문자열이면 '프로젝트 없음'으로 옮긴다
    project_id: str | None = None


@router.patch("/apps/{app_id}")
def update_app(app_id: str, body: AppPatch, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    changes = body.model_dump(exclude_none=True)
    if "project_id" in changes:
        check_project_target(ctx, app.workspace_id, changes["project_id"])
        changes["project_id"] = changes["project_id"] or None
    for k, v in changes.items():
        setattr(app, k, v)
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.update",
        target_type="app",
        target_id=app.id,
        meta=changes,
    )
    ctx.db.commit()
    return svc.app_detail(ctx.db, app)


@router.delete("/apps/{app_id}", status_code=204)
def delete_app(app_id: str, ctx: AppBuilders) -> Response:
    app = svc.get_app(ctx.db, app_id)
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.delete",
        target_type="app",
        target_id=app.id,
        meta={"name": app.name},
    )
    ctx.db.delete(app)
    ctx.db.commit()
    return Response(status_code=204)


class DraftIn(BaseModel):
    graph: dict[str, Any]
    # 누가 고쳤는지(빌더 지표용). 화면 캔버스 자동 저장은 canvas
    source: Literal["canvas", "builder", "import"] = "canvas"


def _parse_graph(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        return Graph.model_validate(raw).dump()
    except ValidationError as exc:
        raise AppError(
            422, "흐름 형식이 올바르지 않아요.", "화면을 새로고침한 뒤 다시 시도하세요."
        ) from exc


@router.put("/apps/{app_id}/draft")
def save_draft(app_id: str, body: DraftIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    app.draft_graph = _parse_graph(body.graph)
    if body.source == "canvas":
        builder_metrics.on_canvas_edit(ctx.db, app.id)
    ctx.db.commit()
    return svc.app_detail(ctx.db, app)


# ---------------- 저장해 둔 테스트 입력 ----------------
MAX_TEST_INPUTS = 20
MAX_TEST_INPUT_BYTES = 20_000


class TestInputItem(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    input: dict[str, Any] = Field(default_factory=dict)


class TestInputsIn(BaseModel):
    items: list[TestInputItem] = Field(max_length=MAX_TEST_INPUTS)


@router.get("/apps/{app_id}/test-inputs")
def list_test_inputs(app_id: str, ctx: AppBuilders) -> list[dict[str, Any]]:
    app = svc.get_app(ctx.db, app_id)
    return list(app.test_inputs or [])


@router.put("/apps/{app_id}/test-inputs")
def save_test_inputs(app_id: str, body: TestInputsIn, ctx: AppBuilders) -> list[dict[str, Any]]:
    app = svc.get_app(ctx.db, app_id)
    items = [i.model_dump() for i in body.items]
    names = [i["name"].strip() for i in items]
    if len(set(names)) != len(names):
        raise AppError(422, "같은 이름의 테스트 입력이 있어요.", "이름을 서로 다르게 지어 주세요.")
    if len(json.dumps(items, ensure_ascii=False)) > MAX_TEST_INPUT_BYTES:
        raise AppError(
            422, "테스트 입력이 너무 길어요.", "긴 글은 줄이거나 저장 개수를 줄여 주세요."
        )
    app.test_inputs = [{"name": n, "input": i["input"]} for n, i in zip(names, items, strict=True)]
    ctx.db.commit()
    return list(app.test_inputs)


def _version_dict(v: WorkflowVersion, with_graph: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": v.id,
        "version": v.version,
        "note": v.note,
        "created_at": v.created_at,
        "created_by": v.created_by,
    }
    if with_graph:
        out["graph"] = v.graph
    return out


@router.get("/apps/{app_id}/versions")
def list_versions(app_id: str, ctx: AppViewers) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.app_id == app_id)
        .order_by(WorkflowVersion.version.desc())
    )
    return [_version_dict(v) for v in rows]


@router.get("/apps/{app_id}/versions/{version}")
def get_version(app_id: str, version: int, ctx: AppViewers) -> dict[str, Any]:
    v = ctx.db.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.app_id == app_id, WorkflowVersion.version == version
        )
    )
    if v is None:
        raise not_found("버전")
    return _version_dict(v, with_graph=True)


class VersionIn(BaseModel):
    graph: dict[str, Any] | None = None
    note: str = Field(default="", max_length=500)


@router.post("/apps/{app_id}/versions", status_code=201)
def create_version(app_id: str, body: VersionIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    graph = _parse_graph(body.graph) if body.graph is not None else (app.draft_graph or {})
    v = svc.save_version(ctx.db, app, graph, body.note, ctx.user.id)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.version_save",
        target_type="app",
        target_id=app.id,
        meta={"version": v.version},
    )
    ctx.db.commit()
    return _version_dict(v)


class ValidateIn(BaseModel):
    graph: dict[str, Any] | None = None


@router.post("/apps/{app_id}/validate")
def validate(app_id: str, body: ValidateIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    graph = body.graph if body.graph is not None else (app.draft_graph or {})
    return svc.validate_for_app(ctx.db, app, graph).model_dump()


class RunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    version: int | None = None


@router.post("/apps/{app_id}/runs", status_code=201)
def create_run(app_id: str, body: RunIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    if body.version is not None:
        v = ctx.db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.app_id == app_id, WorkflowVersion.version == body.version
            )
        )
        if v is None:
            raise not_found("버전")
        run = Run(
            app_id=app.id, version_id=v.id, trigger="test", input=body.input, created_by=ctx.user.id
        )
    else:
        graph = app.draft_graph or {}
        result = svc.validate_for_app(ctx.db, app, graph)
        if not result.valid:
            raise AppError(
                422,
                "흐름에 고칠 부분이 있어 실행하지 못했어요.",
                "빨간 테두리 단계의 오류를 먼저 고치세요.",
                errors=[e.model_dump() for e in result.errors],
            )
        run = Run(
            app_id=app.id,
            trigger="test",
            input=body.input,
            graph_snapshot=graph,
            created_by=ctx.user.id,
        )
    ctx.db.add(run)
    ctx.db.commit()
    enqueue_run(run.id)
    ctx.db.refresh(run)
    return run_dict(run)


@router.get("/apps/{app_id}/runs")
def list_app_runs(
    app_id: str, ctx: AppViewers, limit: int = Query(default=50, ge=1, le=1000)
) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(Run).where(Run.app_id == app_id).order_by(Run.created_at.desc()).limit(limit)
    )
    return [run_dict(r) for r in rows]
