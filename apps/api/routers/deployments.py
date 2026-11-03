"""배포(위젯·공유 링크·API)와 공개 챗 API, 위젯 스크립트."""

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
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
from api.models import App, Conversation, Deployment, Message, Run, User, WorkflowVersion
from api.routers.common import client_ip, public_origin, sse_frame, sse_response
from api.services import apps as app_svc
from api.services.queue import enqueue_run

router = APIRouter(tags=["deployments"])
AppDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="app"))]
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]
DepDeployers = Annotated[Ctx, Depends(require_role(DEPLOY_APPS, via="deployment"))]
CHAT_WAIT_SECONDS = 120


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


def _input_fields(graph: dict[str, Any]) -> list[dict[str, Any]]:
    node = next((n for n in graph.get("nodes", []) if n.get("type") == "input"), None)
    if node is None:
        return []
    return [
        {
            "key": f.get("key"),
            "label": f.get("label") or f.get("key"),
            "type": f.get("type", "text"),
            "required": bool(f.get("required")),
        }
        for f in node.get("data", {}).get("fields", [])
        if f.get("key")
    ]


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


@router.get("/public/apps/{token}")
def public_app(token: str, db: DbDep, user: OptionalUser) -> dict[str, Any]:
    dep, app, version = _load_public(db, token)
    can_use = True
    try:
        _check_access(db, dep, app, user)
    except AppError:
        can_use = False
    return {
        "name": app.name,
        "description": app.description,
        "icon": app.icon,
        "type": app.type,
        "access": dep.access,
        "requires_login": dep.access != "public",
        "can_use": can_use,
        "input_fields": _input_fields(version.graph),
    }


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=4000)
    session_id: str | None = Field(default=None, max_length=100)
    input: dict[str, Any] | None = None


@router.post("/public/apps/{token}/chat")
def public_chat(
    token: str, body: ChatIn, request: Request, db: DbDep, user: OptionalUser
) -> StreamingResponse:
    if not ratelimit.allow(f"chat:{client_ip(request)}"):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    dep, app, version = _load_public(db, token)
    _check_access(db, dep, app, user)
    fields = _input_fields(version.graph)
    conv: Conversation | None = None
    if body.session_id:
        conv = db.scalar(
            select(Conversation).where(
                Conversation.deployment_id == dep.id,
                Conversation.external_session_id == body.session_id,
            )
        )
    if conv is None:
        conv = Conversation(
            app_id=app.id,
            deployment_id=dep.id,
            user_id=user.id if user else None,
            external_session_id=body.session_id or random_token(12),
        )
        db.add(conv)
        db.flush()
    history = [
        {"role": m.role, "content": m.content}
        for m in db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
    ][::-1]
    run_input: dict[str, Any] = dict(body.input or {})
    if fields and body.message:
        run_input.setdefault(str(fields[0]["key"]), body.message)
    run_input["history"] = "\n".join(f"{h['role']}: {h['content']}" for h in history)
    db.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content=body.message or json.dumps(body.input or {}, ensure_ascii=False),
        )
    )
    run = Run(
        app_id=app.id,
        version_id=version.id,
        trigger="chat",
        input=run_input,
        created_by=user.id if user else None,
    )
    db.add(run)
    db.commit()
    session_id = conv.external_session_id or ""
    conv_id = conv.id
    run_id = run.id

    def frames() -> Iterator[str]:
        yield sse_frame("session", {"session_id": session_id})
        yield sse_frame("status", {"message": "답을 만들고 있어요"})
        enqueue_run(run_id)
        deadline = time.time() + CHAT_WAIT_SECONDS
        status = "queued"
        while time.time() < deadline:
            with SessionLocal() as s:
                r = s.get(Run, run_id)
                status = r.status if r else "failed"
                if r is not None and status in ("succeeded", "failed", "waiting_approval"):
                    if status == "succeeded":
                        answer = str((r.output or {}).get("text", "")) or "(답이 비어 있어요)"
                    elif status == "waiting_approval":
                        answer = "담당자의 승인을 기다리고 있어요. 승인되면 처리돼요."
                    else:
                        answer = ""
                    if answer:
                        s.add(
                            Message(
                                conversation_id=conv_id,
                                role="assistant",
                                content=answer,
                                run_id=run_id,
                            )
                        )
                        s.commit()
                        yield sse_frame("answer", {"text": answer})
                    else:
                        yield sse_frame(
                            "error",
                            {
                                "message": "답을 만들지 못했어요.",
                                "hint": "잠시 후 다시 물어보거나 앱 관리자에게 알려 주세요.",
                            },
                        )
                    break
            time.sleep(0.4)
        else:
            yield sse_frame(
                "error",
                {"message": "답이 너무 오래 걸려요.", "hint": "잠시 후 다시 물어봐 주세요."},
            )
        yield sse_frame("done", {"session_id": session_id, "run_id": run_id, "status": status})

    return sse_response(frames())


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
