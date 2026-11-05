"""배포(위젯·공유 링크·API)와 공개 챗 API, 위젯 스크립트, 위젯 모양(v0.4)."""

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
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
from api.models import (
    App,
    Conversation,
    Deployment,
    Membership,
    Message,
    Run,
    StoredFile,
    User,
    WorkflowVersion,
)
from api.routers.common import client_ip, public_origin, sse_frame, sse_response
from api.services import apps as app_svc
from api.services.app_config import merged_features
from api.services.chat import ChatRequest, input_fields, run_chat, start_chat, start_handoff
from api.services.files import save_upload
from api.services.ip_access import normalize as normalize_ips
from api.services.kb_images import with_image_urls
from api.services.queue import enqueue_run

router = APIRouter(tags=["deployments"])
AppDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]
DepDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="deployment"))]


# ---------------- 위젯 모양(v0.4) ----------------
class Appearance(BaseModel):
    """위젯·공유 챗 모양. 비운 값은 기본값을 쓴다."""

    model_config = ConfigDict(extra="forbid")

    primary_color: str = Field(default="#4f46e5", pattern=r"^#[0-9a-fA-F]{6}$")
    position: Literal["right", "left"] = "right"
    launcher_text: str = Field(default="", max_length=20)
    greeting: str = Field(default="", max_length=120)
    open_on_load: bool = False
    width: int = Field(default=380, ge=300, le=640)
    height: int = Field(default=600, ge=400, le=900)
    title: str = Field(default="", max_length=60)
    # v0.8: 링크를 공유할 때 메신저에 뜨는 미리보기(제목·소개 문구·썸네일 파일 id)
    share_title: str = Field(default="", max_length=60)
    share_description: str = Field(default="", max_length=160)
    share_image: str = Field(default="", max_length=64)
    # v0.8: 웹앱 로고(파일 id). 공유 화면·위젯 머리에 보인다
    share_logo: str = Field(default="", max_length=64)


def appearance_of(d: Deployment) -> dict[str, Any]:
    """저장된 값 중 올바른 것만 기본값 위에 얹는다(옛 값이 틀려도 화면이 깨지지 않게)."""
    base = Appearance().model_dump()
    for k, v in (d.appearance or {}).items():
        if k not in base:
            continue
        try:
            base[k] = Appearance.model_validate({**base, k: v}).model_dump()[k]
        except ValueError:
            continue
    return base


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
        "allowed_users": d.allowed_users or [],
        "created_at": d.created_at,
        "share_url": f"{origin}/share/{d.public_token}",
        "widget_snippet": f'<script src="{origin}/api/v1/public/apps/{d.public_token}/widget.js" async></script>',
        "api_url": f"{origin}/api/v1/public/apps/{d.public_token}/chat",
        "appearance": appearance_of(d),
        "allowed_ips": [str(x) for x in (d.allowed_ips or [])],
    }


class DeploymentIn(BaseModel):
    channel: Literal["web_widget", "share_link", "api"] = "share_link"
    access: Literal["workspace", "roles", "public"] = "workspace"
    allowed_roles: list[Role] = Field(default_factory=list)
    # v0.5: 특정 사용자(워크스페이스 멤버 user id). 역할과 함께 쓰면 둘 중 하나만 맞아도 된다
    allowed_users: list[str] = Field(default_factory=list, max_length=500)
    version: int | None = None
    # v0.8: 허용 IP·대역(비우면 제한 없음)
    allowed_ips: list[str] = Field(default_factory=list, max_length=100)


def _members_only(db: Session, workspace_id: str, user_ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(str(u)[:36] for u in user_ids if str(u).strip()))
    if not ids:
        return []
    found = set(
        db.scalars(
            select(Membership.user_id).where(
                Membership.workspace_id == workspace_id, Membership.user_id.in_(ids)
            )
        )
    )
    missing = [u for u in ids if u not in found]
    if missing:
        raise AppError(
            422,
            "워크스페이스 멤버가 아닌 사람이 들어 있어요.",
            "멤버 목록에서 다시 골라 주세요.",
        )
    return ids


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
    if body.access == "roles" and not body.allowed_roles and not body.allowed_users:
        raise AppError(
            422,
            "사용할 수 있는 역할이나 사람을 하나 이상 골라 주세요.",
            "역할 목록에서 체크하거나 사람을 고르세요.",
        )
    users = (
        _members_only(ctx.db, app.workspace_id, body.allowed_users)
        if body.access == "roles"
        else []
    )
    dep = Deployment(
        app_id=app_id,
        version_id=version.id,
        channel=body.channel,
        public_token=random_token(18),
        access=body.access,
        allowed_roles=list(body.allowed_roles) if body.access == "roles" else [],
        allowed_users=users,
        allowed_ips=normalize_ips(body.allowed_ips),
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


class DeploymentPatch(BaseModel):
    appearance: Appearance | None = None
    # v0.5: 누가 쓸 수 있나 바꾸기
    access: Literal["workspace", "roles", "public"] | None = None
    allowed_roles: list[Role] | None = None
    allowed_users: list[str] | None = Field(default=None, max_length=500)
    # v0.8: 허용 IP·대역. []이면 제한을 푼다
    allowed_ips: list[str] | None = Field(default=None, max_length=100)


@router.patch("/deployments/{deployment_id}")
def update_deployment(
    deployment_id: str, body: DeploymentPatch, request: Request, ctx: DepDeployers
) -> dict[str, Any]:
    dep = ctx.db.get(Deployment, deployment_id)
    if dep is None:
        raise not_found("배포")
    app = ctx.db.get(App, dep.app_id)
    if body.allowed_ips is not None:
        ips = normalize_ips(body.allowed_ips)
        if ips != list(dep.allowed_ips or []):
            dep.allowed_ips = ips
            if app is not None:
                audit(
                    ctx.db,
                    workspace_id=app.workspace_id,
                    user_id=ctx.user.id,
                    action="app.deploy_ips",
                    target_type="deployment",
                    target_id=dep.id,
                    meta={"count": len(ips)},
                )
    if body.appearance is not None:
        if body.appearance.share_logo and app is not None:
            from api.services.share_meta import MAX_LOGO_BYTES, logo_ok

            logo = ctx.db.get(StoredFile, body.appearance.share_logo)
            if not logo_ok(logo, app.workspace_id):
                raise AppError(
                    422,
                    "로고로 쓸 수 없는 그림이에요.",
                    f"PNG·JPG·WEBP 그림을 {MAX_LOGO_BYTES // (1024 * 1024)}MB 이하로 올려 주세요.",
                )
        if body.appearance.share_image and app is not None:
            from api.services.share_meta import MAX_IMAGE_BYTES, image_ok

            img = ctx.db.get(StoredFile, body.appearance.share_image)
            if not image_ok(img, app.workspace_id):
                raise AppError(
                    422,
                    "썸네일로 쓸 수 없는 그림이에요.",
                    f"PNG·JPG·WEBP·GIF 그림을 {MAX_IMAGE_BYTES // (1024 * 1024)}MB 이하로 올려 주세요.",
                )
        dep.appearance = body.appearance.model_dump()
    access_changed = any(
        v is not None for v in (body.access, body.allowed_roles, body.allowed_users)
    )
    if access_changed and app is not None:
        access = body.access or dep.access
        roles = list(body.allowed_roles) if body.allowed_roles is not None else dep.allowed_roles
        users = (
            _members_only(ctx.db, app.workspace_id, body.allowed_users)
            if body.allowed_users is not None
            else list(dep.allowed_users or [])
        )
        if access == "roles" and not roles and not users:
            raise AppError(
                422,
                "사용할 수 있는 역할이나 사람을 하나 이상 골라 주세요.",
                "역할 목록에서 체크하거나 사람을 고르세요.",
            )
        dep.access = access
        dep.allowed_roles = list(roles or []) if access == "roles" else []
        dep.allowed_users = users if access == "roles" else []
    if app is not None:
        audit(
            ctx.db,
            workspace_id=app.workspace_id,
            user_id=ctx.user.id,
            action="app.deploy_access" if access_changed else "app.deploy_appearance",
            target_type="deployment",
            target_id=dep.id,
            meta={"access": dep.access} if access_changed else None,
        )
    ctx.db.commit()
    version = ctx.db.get(WorkflowVersion, dep.version_id)
    return _dep(dep, version.version if version else None, public_origin(request))


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
    if (
        dep.access == "roles"
        and role not in (dep.allowed_roles or [])
        and user.id not in (dep.allowed_users or [])
        and role != "owner"
    ):
        raise AppError(
            403,
            "이 앱을 쓸 수 있는 사람으로 지정되지 않았어요.",
            "앱 관리자에게 배포 대상(역할·사람)을 확인해 달라고 요청하세요.",
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
        "appearance": appearance_of(dep),
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
    if _rate_limited(app, f"chat:{app.id}:{client_ip(request)}"):
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


# ---------------- 워크플로우 앱 공유(입력 폼 → 결과), 기능 정의서 앱 유형 ----------------
class FormRunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list, max_length=10)


@router.post("/public/apps/{token}/runs", status_code=202)
def public_form_run(
    token: str, body: FormRunIn, request: Request, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    """공유 링크로 흐름을 한 번 실행한다. 바로 run_id를 돌려주고, 결과는 아래 GET으로 받는다."""
    dep, app, version = _load_public(db, token)
    if _rate_limited(app, f"run:{app.id}:{client_ip(request)}"):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    _check_access(db, dep, app, user)
    run_input = dict(body.input or {})
    if len(json.dumps(run_input, ensure_ascii=False, default=str)) > 20_000:
        raise AppError(413, "입력이 너무 길어요.", "내용을 줄여서 다시 보내 주세요.")
    files = _own_files(db, app, body.files)
    if files:
        field = next((f["key"] for f in input_fields(version.graph) if f["type"] == "file"), None)
        if field:
            run_input.setdefault(str(field), files[0] if len(files) == 1 else files)
    run = Run(
        app_id=app.id,
        version_id=version.id,
        trigger="form",
        input=run_input,
        created_by=user.id if user else None,
    )
    db.add(run)
    db.commit()
    run_id = run.id
    enqueue_run(run_id)
    return {"run_id": run_id, "status": "queued"}


@router.get("/public/apps/{token}/runs/{run_id}")
def public_form_result(token: str, run_id: str, db: DbDep, user: OptionalUser) -> dict[str, Any]:
    """그 공유 링크 앱의 실행 결과만. 단계 입력·출력 같은 내부 값은 보내지 않는다."""
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    run = db.get(Run, run_id)
    if run is None or run.app_id != app.id or run.trigger != "form":
        raise not_found("실행 결과")
    out = run.output or {}
    body: dict[str, Any] = {"run_id": run.id, "status": run.status}
    if run.status == "succeeded":
        body["text"] = str(out.get("text", ""))
        from api.services import run_files

        made = run_files.files_of_run(db, run, app.workspace_id)
        if made:
            body["files"] = run_files.with_public_links(made, app.id, run.id)
    elif run.status == "failed":
        msg = (run.error or "").strip()
        body["error"] = {
            "message": "흐름을 끝까지 실행하지 못했어요.",
            "hint": "입력을 확인하고 다시 실행하거나, 앱을 만든 사람에게 알려 주세요.",
            "detail": msg[:300],
        }
    elif run.status == "waiting_approval":
        body["text"] = "담당자의 확인을 기다리고 있어요. 확인되면 이 화면에 결과가 나와요."
    return body


@router.get("/public/apps/{token}/sessions/{session_id}/messages")
def public_session_messages(
    token: str, session_id: str, db: DbDep, user: OptionalUser
) -> list[dict[str, Any]]:
    """브라우저가 가진 세션 id로 지난 대화를 다시 불러온다(이 배포의 대화만)."""
    dep, app, version = _load_public(db, token)
    _check_access(db, dep, app, user)
    conv = db.scalar(
        select(Conversation).where(
            Conversation.app_id == app.id,
            Conversation.deployment_id == dep.id,
            Conversation.external_session_id == session_id[:100],
        )
    )
    if conv is None:
        raise AppError(404, "지난 대화를 찾을 수 없어요.", "새 대화를 시작하세요.")
    msgs = list(
        db.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )
    )
    from api.services import run_files

    makes_files = run_files.graph_makes_files(version.graph)
    out: list[dict[str, Any]] = []
    for m in msgs:
        item: dict[str, Any] = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
            "feedback": m.feedback,
            "citations": with_image_urls(
                m.citations or [], dep.public_token if dep.access == "public" else None
            ),
            "moderated": bool(m.moderated),
            "annotated": m.annotation_id is not None,
        }
        run = db.get(Run, m.run_id) if makes_files and m.role == "assistant" and m.run_id else None
        if run is not None and run.status == "succeeded" and not m.moderated:
            made = run_files.files_of_run(db, run, app.workspace_id)
            if made:  # 지난 대화를 다시 열면 새로 서명한 링크를 준다
                item["files"] = run_files.with_public_links(made, app.id, run.id)
        out.append(item)
    return out


def _session_conv(db: Session, dep: Deployment, app: App, session_id: str) -> Conversation:
    conv = db.scalar(
        select(Conversation).where(
            Conversation.app_id == app.id,
            Conversation.deployment_id == dep.id,
            Conversation.external_session_id == session_id[:100],
        )
    )
    if conv is None:
        raise AppError(404, "지난 대화를 찾을 수 없어요.", "새 대화를 시작하세요.")
    return conv


@router.get("/public/apps/{token}/sessions/{session_id}/state")
def public_session_state(
    token: str, session_id: str, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    """대화 상태(bot | handoff | closed)와 사람을 기다리는 실행이 있는지. 챗 화면이 주기적으로 본다."""
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    conv = _session_conv(db, dep, app, session_id)
    waiting = db.scalar(
        select(func.count())
        .select_from(Run)
        .join(Message, Message.run_id == Run.id)
        .where(Message.conversation_id == conv.id, Run.status == "waiting_approval")
    )
    last = db.scalar(select(func.max(Message.created_at)).where(Message.conversation_id == conv.id))
    return {"status": conv.status, "waiting": bool(waiting), "last_message_at": last}


@router.post("/public/apps/{token}/sessions/{session_id}/handoff")
def public_request_handoff(
    token: str, session_id: str, request: Request, db: DbDep, user: OptionalUser
) -> dict[str, Any]:
    """'상담원 연결' 버튼: 이 대화를 사람에게 넘긴다(앱에서 상담원 전환을 켠 경우만)."""
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    if _rate_limited(app, f"handoff:{app.id}:{client_ip(request)}"):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    if not (merged_features(app.features).get("handoff") or {}).get("enabled"):
        raise AppError(
            409,
            "이 챗봇은 상담원 연결을 쓰지 않아요.",
            "챗봇에게 다시 물어보거나 관리자에게 문의하세요.",
        )
    conv = _session_conv(db, dep, app, session_id)
    if conv.status == "handoff":
        return {"status": "handoff", "message": None}
    m = start_handoff(db, app, conv, time.time())
    return {"status": "handoff", "message": {"id": m.id, "content": m.content}}


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
    if _rate_limited(app, f"upload:{app.id}:{client_ip(request)}"):
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
  var s = document.currentScript; if (!s || window.__genioWidget) return;
  window.__genioWidget = true;
  var cfg = __CFG__;
  var origin = new URL(s.src).origin;
  var url = origin + "/share/__TOKEN__?embed=1";
  var side = cfg.position === "left" ? "left" : "right";
  var color = cfg.primary_color || "#4f46e5";
  var font = "-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif";
  var opened = false, loaded = false, bubble = null;
  var ICON_CHAT = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var ICON_X = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  var css = document.createElement("style");
  css.textContent =
    ".genio-w-btn{position:fixed;bottom:20px;" + side + ":20px;z-index:2147483646;display:flex;align-items:center;justify-content:center;gap:8px;height:56px;min-width:56px;border:0;border-radius:28px;background:" + color + ";color:#fff;font:600 15px/1 " + font + ";box-shadow:0 6px 20px rgba(0,0,0,.22);cursor:pointer;transition:transform .2s ease,box-shadow .2s ease}" +
    ".genio-w-btn:hover{transform:translateY(-2px) scale(1.03);box-shadow:0 10px 26px rgba(0,0,0,.28)}" +
    ".genio-w-btn:focus-visible{outline:3px solid " + color + "66;outline-offset:3px}" +
    ".genio-w-frame{position:fixed;bottom:88px;" + side + ":20px;width:min(" + cfg.width + "px,calc(100vw - 40px));height:min(" + cfg.height + "px,calc(100vh - 120px));border:0;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.22);background:#fff;z-index:2147483647;opacity:0;visibility:hidden;transform:translateY(12px) scale(.98);transform-origin:bottom " + side + ";transition:opacity .2s ease,transform .2s ease,visibility 0s linear .2s}" +
    ".genio-w-frame.open{opacity:1;visibility:visible;transform:none;transition:opacity .2s ease,transform .2s ease}" +
    ".genio-w-bubble{position:fixed;bottom:88px;" + side + ":20px;max-width:260px;padding:12px 34px 12px 14px;border-radius:14px;background:#fff;color:#0f172a;font:14px/1.45 " + font + ";box-shadow:0 8px 24px rgba(0,0,0,.16);z-index:2147483646;cursor:pointer;animation:genioWIn .3s ease}" +
    ".genio-w-bubble button{position:absolute;top:6px;right:6px;width:24px;height:24px;border:0;background:none;color:#64748b;font-size:18px;line-height:1;cursor:pointer}" +
    "@keyframes genioWIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}" +
    "@media (max-width:480px){.genio-w-frame{top:0;left:0;right:0;bottom:0;width:100vw;height:100dvh;border-radius:0}.genio-w-frame.open~.genio-w-btn{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.genio-w-btn,.genio-w-frame{transition:none}.genio-w-bubble{animation:none}}";

  var frame = document.createElement("iframe");
  frame.className = "genio-w-frame";
  frame.title = (cfg.title || cfg.name || "") + " 챗봇";
  frame.setAttribute("allow", "microphone; clipboard-write");
  frame.setAttribute("aria-hidden", "true");

  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "genio-w-btn";

  function render() {
    btn.innerHTML = opened ? ICON_X : ICON_CHAT;
    if (!opened && cfg.launcher_text) {
      var t = document.createElement("span");
      t.textContent = cfg.launcher_text;
      btn.appendChild(t);
    }
    btn.style.padding = !opened && cfg.launcher_text ? "0 20px 0 16px" : "0";
    btn.setAttribute("aria-label", opened ? "챗봇 닫기" : "챗봇 열기");
    btn.setAttribute("aria-expanded", opened ? "true" : "false");
  }
  function hideBubble() { if (bubble) { bubble.remove(); bubble = null; } }
  function setOpen(v, focus) {
    opened = v;
    if (v && !loaded) { frame.src = url; loaded = true; }
    frame.classList.toggle("open", v);
    frame.setAttribute("aria-hidden", v ? "false" : "true");
    hideBubble();
    render();
    if (focus) { try { (v ? frame : btn).focus(); } catch (e) {} }
  }
  function showBubble() {
    if (opened || !cfg.greeting) return;
    try {
      if (sessionStorage.getItem("genio-greet-__TOKEN__")) return;
      sessionStorage.setItem("genio-greet-__TOKEN__", "1");
    } catch (e) {}
    bubble = document.createElement("div");
    bubble.className = "genio-w-bubble";
    bubble.setAttribute("role", "status");
    var t = document.createElement("span");
    t.textContent = cfg.greeting;
    bubble.appendChild(t);
    var x = document.createElement("button");
    x.type = "button";
    x.setAttribute("aria-label", "인사말 닫기");
    x.textContent = "×";
    x.onclick = function (e) { e.stopPropagation(); hideBubble(); };
    bubble.appendChild(x);
    bubble.onclick = function () { setOpen(true, true); };
    document.body.appendChild(bubble);
  }

  btn.onclick = function () { setOpen(!opened, true); };
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && opened) setOpen(false, true);
  });
  // 챗 화면 안의 닫기 버튼·Esc
  window.addEventListener("message", function (e) {
    if (e.origin === origin && e.data && e.data.type === "genio:close") setOpen(false, true);
  });

  function mount() {
    document.head.appendChild(css);
    document.body.appendChild(frame);
    document.body.appendChild(btn);
    render();
    if (cfg.open_on_load && window.innerWidth > 480) setOpen(true, false);
    else setTimeout(showBubble, 3000);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
"""


@router.get("/public/apps/{token}/widget.js")
def widget_js(token: str, db: DbDep) -> Response:
    dep, app, _ = _load_public(db, token)
    safe = "".join(ch for ch in token if ch.isalnum() or ch in "-_")
    cfg = {**appearance_of(dep), "name": app.name}
    # 스크립트 안에 넣는 JSON: </script> 등으로 빠져나가지 못하게 <, >, & 를 이스케이프
    cfg_js = (
        json.dumps(cfg, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return Response(
        content=WIDGET_JS.replace("__TOKEN__", safe).replace("__CFG__", cfg_js),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )
