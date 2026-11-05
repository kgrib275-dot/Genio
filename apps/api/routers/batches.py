"""v0.8 일괄 실행·단계 하나만 시험.

- 일괄 실행: 표 한 장으로 흐름을 여러 번 실행한다(앱 안: 제작자 이상 200줄, 공유 링크: 50줄·접근 권한 확인).
- 단계 시험: 캔버스에서 고른 단계 하나만 샘플 값으로 실행해 본다(제작자 이상).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, DbDep, require_role
from api.engine.executor import _limits_message
from api.models import App, WorkflowVersion
from api.routers.common import client_ip
from api.routers.deployments import OptionalUser, _check_access, _load_public
from api.services import apps as app_svc
from api.services import batches as svc
from api.services import node_test as nt

router = APIRouter(tags=["batches"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]

CSV_HEADERS = {"X-Content-Type-Options": "nosniff"}


class BatchRow(BaseModel):
    row: int | None = Field(default=None, ge=1, le=100000)
    values: dict[str, Any] = Field(default_factory=dict)


class BatchIn(BaseModel):
    rows: list[BatchRow] = Field(min_length=1, max_length=svc.MAX_ROWS_APP)
    # 오류 있는 줄은 빼고 나머지만 실행
    skip_invalid: bool = False
    # 저장한 버전 번호(없으면 지금 작업본)
    version: int | None = None


def _workflow_only(app: App) -> None:
    if app.type != "workflow":
        raise AppError(
            422,
            "챗 앱은 일괄 실행을 쓸 수 없어요.",
            "흐름(워크플로우) 앱에서 쓰거나, 챗 앱은 대화로 시험하세요.",
        )


def _csv_response(data: bytes, filename: str) -> Response:
    return Response(
        data,
        media_type="text/csv; charset=utf-8",
        headers={
            **CSV_HEADERS,
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        },
    )


# ---------------- 앱 안(제작자 이상) ----------------
def _app_graph(
    ctx: Ctx, app_id: str, version: int | None
) -> tuple[App, dict[str, Any], str | None]:
    """일괄 실행에 쓸 그래프. 저장한 버전이 정해지면 그 버전, 아니면 검사를 통과한 작업본."""
    app = app_svc.get_app(ctx.db, app_id)
    _workflow_only(app)
    if version is not None:
        v = ctx.db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.app_id == app_id, WorkflowVersion.version == version
            )
        )
        if v is None:
            raise AppError(404, "버전을 찾을 수 없어요.", "버전 목록을 새로고침해 다시 고르세요.")
        return app, dict(v.graph or {}), v.id
    graph = app.draft_graph or {}
    result = app_svc.validate_for_app(ctx.db, app, graph)
    if not result.valid:
        raise AppError(
            422,
            "흐름에 고칠 부분이 있어 실행하지 못했어요.",
            "빨간 테두리 단계의 오류를 먼저 고치세요.",
            errors=[e.model_dump() for e in result.errors],
        )
    return app, dict(graph), None


@router.get("/apps/{app_id}/batches/template.csv")
def app_template(app_id: str, ctx: AppBuilders) -> Response:
    app = app_svc.get_app(ctx.db, app_id)
    _workflow_only(app)
    fields = svc.batch_fields(app.draft_graph or {})
    return _csv_response(svc.template_csv(fields), "batch-template.csv")


@router.post("/apps/{app_id}/batches/preview")
async def app_preview(
    app_id: str, ctx: AppBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    _workflow_only(app)
    fields = svc.batch_fields(app.draft_graph or {})
    content = await file.read(svc.MAX_FILE_BYTES + 1)
    return {
        "fields": fields,
        "max_rows": svc.MAX_ROWS_APP,
        **svc.parse_upload(file.filename or "", content, fields, svc.MAX_ROWS_APP),
    }


@router.post("/apps/{app_id}/batches", status_code=201)
def app_create(app_id: str, body: BatchIn, ctx: AppBuilders) -> dict[str, Any]:
    app, graph, version_id = _app_graph(ctx, app_id, body.version)
    fields = svc.batch_fields(graph)
    blocked = _limits_message(ctx.db, app)
    if blocked:
        raise AppError(429, blocked, "관리 > 사용량에서 한도를 확인하세요.")
    vid, snap = svc.graph_ref(ctx.db, app, version_id)
    batch_id, total = svc.create_batch(
        ctx.db,
        app,
        rows=[r.model_dump() for r in body.rows],
        fields=fields,
        version_id=vid,
        snapshot=snap,
        user_id=ctx.user.id,
        source="app",
        max_rows=svc.MAX_ROWS_APP,
        skip_invalid=body.skip_invalid,
    )
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.batch_run",
        target_type="app",
        target_id=app.id,
        meta={"batch_id": batch_id, "rows": total},
    )
    ctx.db.commit()
    return {"batch_id": batch_id, "total": total}


@router.get("/apps/{app_id}/batches/{batch_id}")
def app_status(app_id: str, batch_id: str, ctx: AppViewers) -> dict[str, Any]:
    return svc.batch_status(ctx.db, app_id, batch_id, public=False)


@router.post("/apps/{app_id}/batches/{batch_id}/cancel")
def app_cancel(app_id: str, batch_id: str, ctx: AppBuilders) -> dict[str, Any]:
    return {"cancelled": svc.cancel_batch(ctx.db, app_id, batch_id)}


@router.get("/apps/{app_id}/batches/{batch_id}/results.csv")
def app_results(app_id: str, batch_id: str, ctx: AppViewers) -> Response:
    status = svc.batch_status(ctx.db, app_id, batch_id, public=False)
    fields = svc.batch_input_fields(ctx.db, app_id, batch_id)
    return _csv_response(svc.results_csv(status, fields), "batch-results.csv")


# ---------------- 공유 링크(로그인 없이도, 접근 권한은 확인) ----------------
def _public_ctx(
    db: Any, token: str, user: Any, request: Request, *, limit: int | None = 6
) -> tuple[Any, App, Any]:
    dep, app, version = _load_public(db, token)
    if limit and not ratelimit.allow(f"batch:{app.id}:{client_ip(request)}", limit):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    _check_access(db, dep, app, user)
    _workflow_only(app)
    return dep, app, version


@router.get("/public/apps/{token}/batches/template.csv")
def public_template(token: str, request: Request, db: DbDep, user: OptionalUser) -> Response:
    _, _, version = _public_ctx(db, token, user, request, limit=None)
    return _csv_response(
        svc.template_csv(svc.batch_fields(dict(version.graph or {}))), "batch-template.csv"
    )


@router.post("/public/apps/{token}/batches/preview")
async def public_preview(
    token: str,
    request: Request,
    db: DbDep,
    user: OptionalUser,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    _, _, version = _public_ctx(db, token, user, request)
    fields = svc.batch_fields(dict(version.graph or {}))
    content = await file.read(svc.MAX_FILE_BYTES + 1)
    return {
        "fields": fields,
        "max_rows": svc.MAX_ROWS_PUBLIC,
        **svc.parse_upload(file.filename or "", content, fields, svc.MAX_ROWS_PUBLIC),
    }


@router.post("/public/apps/{token}/batches", status_code=201)
def public_create(
    token: str, body: BatchIn, request: Request, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    _, app, version = _public_ctx(db, token, user, request)
    if len(body.rows) > svc.MAX_ROWS_PUBLIC:
        raise AppError(
            422,
            f"공유 링크에서는 한 번에 {svc.MAX_ROWS_PUBLIC}건까지 실행할 수 있어요.",
            "파일을 나눠서 올리거나, 앱 안에서 실행하세요.",
        )
    if svc.active_public_batches(db, app.id) >= svc.MAX_ACTIVE_PUBLIC_BATCHES:
        raise AppError(
            429,
            "지금 처리 중인 일괄 실행이 많아요.",
            "진행 중인 실행이 끝난 뒤 다시 시도하세요.",
        )
    blocked = _limits_message(db, app)
    if blocked:
        raise AppError(429, "지금은 실행할 수 없어요.", "앱을 만든 사람에게 알려 주세요.")
    fields = svc.batch_fields(dict(version.graph or {}))
    batch_id, total = svc.create_batch(
        db,
        app,
        rows=[r.model_dump() for r in body.rows],
        fields=fields,
        version_id=version.id,
        snapshot=None,
        user_id=user.id if user else None,
        source="public",
        max_rows=svc.MAX_ROWS_PUBLIC,
        skip_invalid=body.skip_invalid,
    )
    return {"batch_id": batch_id, "total": total}


@router.get("/public/apps/{token}/batches/{batch_id}")
def public_status(
    token: str, batch_id: str, request: Request, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    _, app, _ = _public_ctx(db, token, user, request, limit=None)
    return svc.batch_status(db, app.id, batch_id, public=True)


@router.post("/public/apps/{token}/batches/{batch_id}/cancel")
def public_cancel(
    token: str, batch_id: str, request: Request, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    _, app, _ = _public_ctx(db, token, user, request, limit=None)
    return {"cancelled": svc.cancel_batch(db, app.id, batch_id)}


@router.get("/public/apps/{token}/batches/{batch_id}/results.csv")
def public_results(
    token: str, batch_id: str, request: Request, db: DbDep, user: OptionalUser
) -> Response:
    _, app, _ = _public_ctx(db, token, user, request, limit=None)
    status = svc.batch_status(db, app.id, batch_id, public=True)
    fields = svc.batch_input_fields(db, app.id, batch_id)
    return _csv_response(svc.results_csv(status, fields), "batch-results.csv")


# ---------------- 단계 하나만 시험(제작자 이상) ----------------
class NodeTestInputsIn(BaseModel):
    # 아직 저장하지 않은 설정 패널의 값
    data: dict[str, Any] | None = None


class NodeTestIn(NodeTestInputsIn):
    # {"n1": {"message": "..."}, "input": {...}, "conv": {...}}. 안 보내면 최근 성공한 실행의 값
    values: dict[str, dict[str, Any]] | None = None


@router.post("/apps/{app_id}/nodes/{node_id}/test-inputs")
def node_test_inputs(
    app_id: str, node_id: str, body: NodeTestInputsIn, ctx: AppBuilders
) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    return nt.test_inputs(ctx.db, app, node_id, body.data)


@router.post("/apps/{app_id}/nodes/{node_id}/test")
def node_test(app_id: str, node_id: str, body: NodeTestIn, ctx: AppBuilders) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    return nt.run_test(ctx.db, app, node_id, body.values, body.data)
