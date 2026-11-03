"""배포(위젯·공유 링크·API)와 공개 챗 API, 위젯 스크립트."""

from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.core.security import random_token
from api.db import SessionLocal
from api.deps import (
    DEPLOY_APPS,
    VIEW_RUNS,
    Ctx,
    DbDep,
    Role,
    get_optional_user,
    membership_role,
    require_role,
)
from api.models import App, Conversation, Deployment, Message, StoredFile, User, WorkflowVersion
from api.routers.common import client_ip, public_origin, sse_frame, sse_response
from api.services import apps as app_svc
from api.services.app_config import merged_features
from api.services.chat import ChatRequest, input_fields, run_chat, start_chat
from api.services.files import save_upload

router = APIRouter(tags=["deployments"])
AppDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]
DepDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="deployment"))]


def _dep(d: Deployment, version: int | None, origin: str) -> dict[str, Any]:
    return {
        "id": d.id,
        "app_id": d.app_id,
        "version_id": d.version_id,
        "version": version,
        "channel": d.channel,
        "public_token": d.public_token,
        "access": d.access,
        "allowed_roles": d.allowed_roles or [],
        "created_at": d.created_at,
        "share_url": f"{origin}/share/{d.public_token}",
        "widget_snippet": f'<script src="{origin}/api/v1/public/apps/{d.public_token}/widget.js" async></script>',
        "api_url": f"{origin}/api/v1/public/apps/{d.public_token}/chat",
    }


class DeploymentIn(BaseModel):
    channel: Literal["web_widget", "share_link", "api"] = "share_link"
    access: Literal["workspace", "roles", "public"] = "workspace"
    allowed_roles: list[Role] = Field(default_factory=list)
    version: int | None = None


@router.post("/apps/{app_id}/deployments", status_code=201)
def create_deployment(
    app_id: str, body: DeploymentIn, request: Request, ctx: AppDeployers
) -> dict[str, Any]:
    app = app_svc.get_app(ctx.db, app_id)
    if body.version is not None:
        version = ctx.db.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.app_id == app_id, WorkflowVersion.version == body.version
            )
        )
    else:
        version = app_svc.latest_version(ctx.db, app_id)
    if version is None:
        raise AppError(
            422,
            "저장된 버전이 없어 배포할 수 없어요.",
            "빌더 화면에서 '버전 저장'을 먼저 누르세요.",
        )
    if body.access == "roles" and not body.allowed_roles:
        raise AppError(
            422, "사용할 수 있는 역할을 하나 이상 골라 주세요.", "역할 목록에서 체크하세요."
        )
    dep = Deployment(
        app_id=app_id,
        version_id=version.id,
        channel=body.channel,
        public_token=random_token(18),
        access=body.access,
        allowed_roles=list(body.allowed_roles) if body.access == "roles" else [],
    )
    ctx.db.add(dep)
    app.status = "published"
    audit(
        ctx.db,
        workspace_id=app.workspace_id,
        user_id=ctx.user.id,
        action="app.deploy",
        target_type="deployment",
        target_id=dep.id,
        meta={"channel": body.channel, "access": body.access, "version": version.version},
    )
    ctx.db.commit()
    return _dep(dep, version.version, public_origin(request))


@router.get("/apps/{app_id}/deployments")
def list_deployments(app_id: str, request: Request, ctx: AppViewers) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(Deployment, WorkflowVersion.version)
        .join(WorkflowVersion, WorkflowVersion.id == Deployment.version_id)
        .where(Deployment.app_id == app_id)
        .order_by(Deployment.created_at.desc())
    ).all()
    origin = public_origin(request)
    return [_dep(d, v, origin) for d, v in rows]


@router.delete("/deployments/{deployment_id}", status_code=204)
def delete_deployment(deployment_id: str, ctx: DepDeployers) -> Response:
    dep = ctx.db.get(Deployment, deployment_id)
    if dep is None:
        raise not_found("배포")
    app = ctx.db.get(App, dep.app_id)
    ctx.db.delete(dep)
    ctx.db.flush()
    if app is not None:
        remaining = ctx.db.scalar(select(Deployment.id).where(Deployment.app_id == app.id).limit(1))
        if remaining is None:
            app.status = "draft"
        audit(
            ctx.db,
            workspace_id=app.workspace_id,
            user_id=ctx.user.id,
            action="app.undeploy",
            target_type="deployment",
            target_id=deployment_id,
        )
    ctx.db.commit()
    return Response(status_code=204)


# ---------------- 공개 ----------------
def _load_public(db: Session, token: str) -> tuple[Deployment, App, WorkflowVersion]:
    dep = db.scalar(select(Deployment).where(Deployment.public_token == token))
    if dep is None:
        raise AppError(
            404, "배포된 앱을 찾을 수 없어요.", "링크가 맞는지 확인하거나 앱 관리자에게 문의하세요."
        )
    app = db.get(App, dep.app_id)
    version = db.get(WorkflowVersion, dep.version_id)
    if app is None or version is None:
        raise AppError(404, "배포된 앱을 찾을 수 없어요.", "앱 관리자에게 문의하세요.")
    return dep, app, version


def _check_access(db: Session, dep: Deployment, app: App, user: User | None) -> None:
    if dep.access == "public":
        return
    if user is None:
        raise AppError(
            401, "이 앱은 로그인한 멤버만 쓸 수 있어요.", "로그인한 뒤 다시 열어 주세요."
        )
    role = membership_role(db, user.id, app.workspace_id)
    if role is None:
        raise AppError(
            403,
            "이 앱을 쓸 수 있는 워크스페이스 멤버가 아니에요.",
            "앱 관리자에게 초대를 요청하세요.",
        )
    if dep.access == "roles" and role not in (dep.allowed_roles or []) and role != "owner":
        raise AppError(
            403,
            "내 역할로는 이 앱을 쓸 수 없어요.",
            "앱 관리자에게 배포 대상 역할을 확인해 달라고 요청하세요.",
        )


_input_fields = input_fields


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


@router.get("/public/apps/{token}")
def public_app(token: str, db: DbDep, user: OptionalUser) -> dict[str, Any]:
    dep, app, version = _load_public(db, token)
    can_use = True
    try:
        _check_access(db, dep, app, user)
    except AppError:
        can_use = False
    f = merged_features(app.features)
    return {
        "name": app.name,
        "description": app.description,
        "icon": app.icon,
        "type": app.type,
        "access": dep.access,
        "requires_login": dep.access != "public",
        "can_use": can_use,
        "input_fields": _input_fields(version.graph),
        "features": {
            "opening_statement": f["opening_statement"],
            "suggested_questions": f["suggested_questions"],
            "follow_up": f["follow_up"],
            "citations": f["citations"],
            "speech": f["speech"],
            "file_upload": f["file_upload"],
        },
    }


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=4000)
    session_id: str | None = Field(default=None, max_length=100)
    input: dict[str, Any] | None = None
    files: list[str] = Field(default_factory=list, max_length=10)


def _rate_limited(app: App, key: str) -> bool:
    ws = app.workspace_id
    limit = None
    from api.models import Workspace

    with SessionLocal() as s:
        w = s.get(Workspace, ws)
        if w is not None:
            limit = (w.settings or {}).get("public_rate_limit_per_minute")
    return not ratelimit.allow(key, int(limit) if limit else None)


@router.post("/public/apps/{token}/chat")
def public_chat(
    token: str, body: ChatIn, request: Request, db: DbDep, user: OptionalUser
) -> StreamingResponse:
    dep, app, version = _load_public(db, token)
    if _rate_limited(app, f"chat:{client_ip(request)}"):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    _check_access(db, dep, app, user)
    files = _own_files(db, app, body.files)
    req = ChatRequest(
        app=app,
        version=version,
        deployment=dep,
        user_id=user.id if user else None,
        message=body.message,
        session_id=body.session_id,
        inputs=dict(body.input or {}),
        files=files,
    )
    conv, _ = start_chat(db, req)
    conv_id, session_id = conv.id, conv.external_session_id or ""
    app_id, version_id, user_id = app.id, version.id, req.user_id

    def frames() -> Iterator[str]:
        yield sse_frame("session", {"session_id": session_id})
        for name, data in run_chat(
            conv_id, app_id, version_id, user_id, body.message, req.inputs, files
        ):
            yield sse_frame(name, data)

    return sse_response(frames())


def _own_files(db: Session, app: App, ids: list[str]) -> list[str]:
    out = []
    for fid in ids:
        f = db.get(StoredFile, fid)
        if f is None or f.workspace_id != app.workspace_id:
            raise AppError(404, "첨부한 파일을 찾을 수 없어요.", "파일을 다시 올려 주세요.")
        out.append(f.id)
    return out


@router.post("/public/apps/{token}/files")
async def public_upload(
    token: str, request: Request, db: DbDep, user: OptionalUser, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    if not merged_features(app.features)["file_upload"]["enabled"]:
        raise AppError(
            403,
            "이 앱은 파일 첨부를 받지 않아요.",
            "앱 관리자에게 파일 첨부를 켜 달라고 요청하세요.",
        )
    if _rate_limited(app, f"upload:{client_ip(request)}"):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    return await save_upload(
        db, app.workspace_id, file, app_id=app.id, user_id=user.id if user else None
    )


class FeedbackIn(BaseModel):
    rating: Literal["like", "dislike"] | None = None
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/public/apps/{token}/messages/{message_id}/feedback")
def public_feedback(
    token: str, message_id: str, body: FeedbackIn, db: DbDep, user: OptionalUser
) -> dict[str, bool]:
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    msg = db.get(Message, message_id)
    conv = db.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or conv is None or conv.app_id != app.id or msg.role != "assistant":
        raise AppError(404, "답변을 찾을 수 없어요.", "화면을 새로고침하세요.")
    msg.feedback = body.rating
    msg.feedback_comment = body.comment
    db.commit()
    return {"ok": True}


WIDGET_JS = """(function(){
  var s = document.currentScript; if(!s) return;
  var origin = new URL(s.src).origin;
  var url = origin + "/share/__TOKEN__?embed=1";
  var btn = document.createElement("button");
  btn.setAttribute("aria-label", "챗봇 열기");
  btn.textContent = "💬";
  btn.style.cssText = "position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:28px;border:0;background:#2563eb;color:#fff;font-size:24px;box-shadow:0 4px 14px rgba(0,0,0,.25);cursor:pointer;z-index:2147483646";
  var frame = document.createElement("iframe");
  frame.src = url; frame.title = "챗봇";
  frame.style.cssText = "position:fixed;right:20px;bottom:88px;width:min(380px,calc(100vw - 40px));height:min(560px,calc(100vh - 120px));border:1px solid #e5e7eb;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.2);display:none;z-index:2147483647;background:#fff";
  btn.onclick = function(){ frame.style.display = frame.style.display === "none" ? "block" : "none"; };
  document.body.appendChild(frame); document.body.appendChild(btn);
})();
"""


@router.get("/public/apps/{token}/widget.js")
def widget_js(token: str, db: DbDep) -> Response:
    _load_public(db, token)
    safe = "".join(ch for ch in token if ch.isalnum() or ch in "-_")
    return Response(
        content=WIDGET_JS.replace("__TOKEN__", safe),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )
