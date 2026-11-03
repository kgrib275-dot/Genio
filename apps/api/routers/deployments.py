"""배포(위젯·공유 링크·API)와 공개 챗 API, 위젯 스크립트, 위젯 모양(v0.4)."""

import json
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
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
        "created_at": d.created_at,
        "share_url": f"{origin}/share/{d.public_token}",
        "widget_snippet": f'<script src="{origin}/api/v1/public/apps/{d.public_token}/widget.js" async></script>',
        "api_url": f"{origin}/api/v1/public/apps/{d.public_token}/chat",
        "appearance": appearance_of(d),
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


class DeploymentPatch(BaseModel):
    appearance: Appearance


@router.patch("/deployments/{deployment_id}")
def update_deployment(
    deployment_id: str, body: DeploymentPatch, request: Request, ctx: DepDeployers
) -> dict[str, Any]:
    dep = ctx.db.get(Deployment, deployment_id)
    if dep is None:
        raise not_found("배포")
    dep.appearance = body.appearance.model_dump()
    app = ctx.db.get(App, dep.app_id)
    if app is not None:
        audit(
            ctx.db,
            workspace_id=app.workspace_id,
            user_id=ctx.user.id,
            action="app.deploy_appearance",
            target_type="deployment",
            target_id=dep.id,
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


@router.get("/public/apps/{token}/sessions/{session_id}/messages")
def public_session_messages(
    token: str, session_id: str, db: DbDep, user: OptionalUser
) -> list[dict[str, Any]]:
    """브라우저가 가진 세션 id로 지난 대화를 다시 불러온다(이 배포의 대화만)."""
    dep, app, _ = _load_public(db, token)
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
    msgs = db.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
            "feedback": m.feedback,
            "citations": m.citations or [],
            "moderated": bool(m.moderated),
            "annotated": m.annotation_id is not None,
        }
        for m in msgs
    ]


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
