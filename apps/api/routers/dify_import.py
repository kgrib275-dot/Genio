"""v0.8 Dify 앱 가져오기: Dify DSL(.yml) 파일을 올리면 제니오 앱(초안)과 변환 보고서를 돌려준다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from api.core.audit import audit
from api.core.errors import AppError
from api.deps import EDIT_APPS, Ctx, require_role
from api.engine.validator import validate_graph
from api.models import App
from api.routers.projects import check_project_target
from api.schemas.graph import Graph
from api.services import apps as svc
from api.services.app_config import patch_features, store_env_vars
from api.services.dify_import import MAX_BYTES, convert

router = APIRouter(tags=["dify-import"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


def _import(ctx: Ctx, ws: str, raw: bytes, project_id: str | None) -> dict[str, Any]:
    check_project_target(ctx, ws, project_id)
    conv = convert(raw)
    try:
        graph = Graph.model_validate(conv.graph).dump()
    except ValueError:
        raise AppError(
            422,
            "변환한 흐름의 형식이 올바르지 않아요.",
            "이 파일을 개발팀에 알려 주세요. 다른 앱 파일은 가져올 수 있어요.",
        ) from None
    # 남은 문제는 막지 않고 보고서에 적는다(앱은 늘 초안으로 만들어진다)
    result = validate_graph(graph, svc.validation_env(ctx.db, ws))
    conv.report.validation_errors = [
        {"node": e.node_id or "", "message": e.message} for e in result.errors
    ]
    app = App(
        workspace_id=ws,
        name=conv.name,
        slug=svc.slugify(conv.name),
        type=conv.app_type,
        description=conv.description,
        icon=conv.icon,
        status="draft",
        created_by=ctx.user.id,
        draft_graph=graph,
        features=patch_features({}, conv.features),
        env_vars=store_env_vars(conv.env_vars, []),
        project_id=project_id or None,
    )
    ctx.db.add(app)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="app.import_dify",
        target_type="app",
        target_id=app.id,
        meta={"name": app.name, "mode": conv.report.mode},
    )
    ctx.db.commit()
    return {"app": svc.app_detail(ctx.db, app), "report": conv.report.dump()}


@router.post("/workspaces/{ws}/apps/import-dify", status_code=201)
async def import_dify(ws: str, request: Request, ctx: WsBuilders) -> dict[str, Any]:
    """파일(multipart `file`, 선택 `project_id`) 또는 JSON `{text, project_id}`로 가져온다."""
    too_big = AppError(
        413, "파일이 너무 커요(최대 2MB).", "Dify에서 내보낸 앱 파일(.yml)만 올려 주세요."
    )
    if int(request.headers.get("content-length") or 0) > MAX_BYTES + 64 * 1024:
        raise too_big
    ctype = request.headers.get("content-type", "")
    project_id: str | None = None
    raw: bytes
    if ctype.startswith("multipart/"):
        form = await request.form()
        up = form.get("file")
        if not isinstance(up, UploadFile):
            raise AppError(422, "올린 파일이 없어요.", "Dify에서 내보낸 .yml 파일을 골라 주세요.")
        raw = await up.read(MAX_BYTES + 1)
        pid = form.get("project_id")
        project_id = str(pid) if isinstance(pid, str) and pid else None
    else:
        try:
            body = await request.json()
        except ValueError:
            raise AppError(
                422, "요청을 읽지 못했어요.", "파일을 올리거나 text에 YAML 글을 넣어 보내세요."
            ) from None
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise AppError(
                422, "가져올 글이 없어요.", "파일을 올리거나 text에 YAML 글을 넣어 보내세요."
            )
        raw = body["text"].encode("utf-8")
        pid = body.get("project_id")
        project_id = str(pid) if isinstance(pid, str) and pid else None
    if len(raw) > MAX_BYTES:
        raise too_big
    return await run_in_threadpool(_import, ctx, ws, raw, project_id)
