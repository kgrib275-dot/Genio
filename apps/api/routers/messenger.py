"""슬랙·팀즈에서 앱 부르기: 설정(제작자 이상)과 받는 주소(서명으로만 믿는다)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.db import SessionLocal
from api.deps import EDIT_APPS, Ctx, DbDep, require_role
from api.engine import safe_http
from api.models import App, Deployment, WorkflowVersion
from api.routers.common import client_ip, public_origin
from api.routers.deployments import _check_open, _load_public
from api.services import messenger as svc
from api.services.chat import ChatRequest, run_chat, start_chat
from nodes import NodeError

log = logging.getLogger("genio.messenger")
router = APIRouter(tags=["messenger"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
RATE_PER_MINUTE = 30


def _share_deployment(db: Session, app_id: str) -> Deployment:
    dep = db.scalar(
        select(Deployment)
        .where(Deployment.app_id == app_id, Deployment.channel == "share_link")
        .order_by(Deployment.created_at.desc())
    )
    if dep is None:
        raise AppError(
            409,
            "공유 링크로 배포한 뒤에 메신저를 연결할 수 있어요.",
            "배포·설정에서 '공유 링크'로 먼저 배포하세요.",
        )
    return dep


def _urls(request: Request, dep: Deployment) -> dict[str, str]:
    origin = public_origin(request)
    return {
        "slack_url": f"{origin}/api/v1/public/messenger/{dep.public_token}/slack",
        "teams_url": f"{origin}/api/v1/public/messenger/{dep.public_token}/teams",
    }


@router.get("/apps/{app_id}/messenger")
def messenger_status(app_id: str, request: Request, ctx: AppBuilders) -> dict[str, Any]:
    dep = ctx.db.scalar(
        select(Deployment)
        .where(Deployment.app_id == app_id, Deployment.channel == "share_link")
        .order_by(Deployment.created_at.desc())
    )
    if dep is None:
        return {"deployed": False}  # 화면이 '먼저 배포하세요'를 보여 준다(오류가 아니다)
    return {"deployed": True, **_urls(request, dep), **svc.status(dep)}


class SecretIn(BaseModel):
    secret: str = Field(min_length=1, max_length=500)


@router.put("/apps/{app_id}/messenger/{provider}")
def set_messenger(
    app_id: str, provider: str, body: SecretIn, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    dep = _share_deployment(ctx.db, app_id)
    if _closed_message(dep):
        raise AppError(
            422,
            "공개 범위가 제한된 앱은 메신저에 연결할 수 없어요.",
            "배포·설정에서 '누가 쓸 수 있나요'를 '누구나'로 바꾼 뒤 다시 연결하세요. 연결하면 슬랙·팀즈를 쓰는 누구나 이 앱에 물어볼 수 있어요.",
        )
    svc.set_secret(dep, provider, body.secret)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="app.messenger_set",
        target_type="app",
        target_id=app_id,
        meta={"provider": provider},
    )
    ctx.db.commit()
    return {"deployed": True, **_urls(request, dep), **svc.status(dep)}


@router.delete("/apps/{app_id}/messenger/{provider}")
def clear_messenger(
    app_id: str, provider: str, request: Request, ctx: AppBuilders
) -> dict[str, Any]:
    if provider not in svc.PROVIDERS:
        raise not_found("메신저")
    dep = _share_deployment(ctx.db, app_id)
    svc.clear_secret(dep, provider)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="app.messenger_clear",
        target_type="app",
        target_id=app_id,
        meta={"provider": provider},
    )
    ctx.db.commit()
    return {"deployed": True, **_urls(request, dep), **svc.status(dep)}


# ---------------- 받는 주소(슬랙·팀즈가 부른다) ----------------
def _answer(dep_id: str, session_key: str, question: str) -> str:
    """앱에 물어 답 글을 돌려준다(실패하면 사람이 읽을 안내 문장)."""
    with SessionLocal() as db:
        dep = db.get(Deployment, dep_id)
        if dep is None:
            return "앱을 찾지 못했어요."
        app = db.get(App, dep.app_id)
        version = db.get(WorkflowVersion, dep.version_id)
        if app is None or version is None:
            return "앱을 찾지 못했어요."
        try:
            _check_open(app)
        except AppError as exc:
            return f"{exc.message} {exc.hint}".strip()
        req = ChatRequest(
            app=app,
            version=version,
            deployment=dep,
            user_id=None,
            message=question,
            session_id=session_key,
        )
        conv, _ = start_chat(db, req)
        conv_id = conv.id
        app_id, version_id = app.id, version.id
    answer = ""
    for name, data in run_chat(conv_id, app_id, version_id, None, question, {}, []):
        if name in ("answer", "moderated", "annotated") and isinstance(data, dict):
            answer = str(data.get("text", ""))
        elif name == "error" and isinstance(data, dict):
            return f"{data.get('message', '답하지 못했어요.')} {data.get('hint', '')}".strip()
    return answer or "답을 만들지 못했어요. 잠시 뒤에 다시 물어봐 주세요."


def _post_slack(response_url: str, text: str) -> None:
    try:
        safe_http.request(
            "POST",
            response_url,
            body={"response_type": "in_channel", "replace_original": True, "text": text[:3000]},
            allowed_domains=list(svc.SLACK_RESPONSE_HOSTS),
        )
    except NodeError:
        log.warning("슬랙에 답을 돌려보내지 못했어요.")
    except Exception:
        log.exception("슬랙 답 전송 실패")


def _secret_or_401(
    db: Session, token: str, provider: str, request: Request
) -> tuple[Deployment, str]:
    """연결된 앱과 서명 비밀값을 찾는다. 서명을 확인하기 전에는 보낸 주소별로만 제한을 건다
    (앱 단위 제한을 먼저 쓰면 공유 링크를 아는 누구나 정상 슬랙 명령을 막을 수 있다)."""
    if not ratelimit.allow(f"msgip:{client_ip(request)}", RATE_PER_MINUTE * 2):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")
    dep, _app, _ = _load_public(db, token)
    secret = svc.get_secret(dep, provider)
    if secret is None:
        # 연결하지 않은 앱은 있는지 없는지도 알려 주지 않는다
        raise AppError(404, "연결된 메신저가 아니에요.", "앱 설정에서 메신저 연결을 확인하세요.")
    return dep, secret


def _check_app_limit(dep: Deployment) -> None:
    """서명이 맞은 요청에만 앱 단위 제한을 건다."""
    if not ratelimit.allow(f"msg:{dep.app_id}", RATE_PER_MINUTE):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요.")


def _closed_message(dep: Deployment) -> str | None:
    """공개 범위가 제한된 앱은 메신저로 열지 않는다(메신저에서는 누가 묻는지 알 수 없다)."""
    if dep.access != "public" or (dep.allowed_ips or []):
        return (
            "이 앱은 공개 범위가 제한돼 있어 메신저에서는 쓸 수 없어요. "
            "앱 담당자에게 '누가 쓸 수 있나요'를 '누구나'로 바꿔 달라고 요청하세요."
        )
    return None


def _duplicate(raw: bytes) -> bool:
    """같은 요청이 다시 오면(슬랙·팀즈의 재시도, 가로챈 요청의 재전송) 한 번만 처리한다."""
    key = "msgdup:" + hashlib.sha256(raw).hexdigest()
    return not ratelimit.allow(key, 1, window=300)


@router.post("/public/messenger/{token}/slack")
async def slack_command(
    token: str, request: Request, db: DbDep, background: BackgroundTasks
) -> JSONResponse:
    dep, secret = await run_in_threadpool(_secret_or_401, db, token, "slack", request)
    raw = await request.body()
    if len(raw) > 20_000 or not svc.verify_slack(
        secret,
        request.headers.get("x-slack-request-timestamp", ""),
        request.headers.get("x-slack-signature", ""),
        raw,
    ):
        raise AppError(
            401, "슬랙에서 온 요청인지 확인하지 못했어요.", "Signing Secret을 확인하세요."
        )
    _check_app_limit(dep)
    closed = _closed_message(dep)
    if closed:
        return JSONResponse({"response_type": "ephemeral", "text": closed})
    if _duplicate(raw):
        # 슬랙이 3초 안에 답을 못 받아 다시 보낸 요청 등: 이미 처리 중이니 조용히 넘긴다
        return JSONResponse({"response_type": "ephemeral", "text": "이미 찾아보는 중이에요."})
    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items() if v}
    question = svc.clean_question(form.get("text", ""))
    if not question:
        return JSONResponse(
            {
                "response_type": "ephemeral",
                "text": "궁금한 것을 함께 적어 주세요. 예: /제니오 연차는 며칠이에요?",
            }
        )
    who = f"{form.get('team_id', '')}:{form.get('user_id', '')}"
    session = svc.session_key("slack", secret, who)
    response_url = form.get("response_url", "")
    dep_id = dep.id
    if not svc.valid_slack_response_url(response_url):
        # 답을 돌려보낼 곳이 없으면 바로 답한다(3초를 넘기면 슬랙이 오류로 보여 줘요)
        text = await run_in_threadpool(_answer, dep_id, session, question)
        return JSONResponse({"response_type": "in_channel", "text": text})

    def deliver() -> None:
        _post_slack(response_url, _answer(dep_id, session, question))

    background.add_task(deliver)
    return JSONResponse({"response_type": "ephemeral", "text": "찾아보는 중이에요… 잠시만요."})


@router.post("/public/messenger/{token}/teams")
async def teams_message(token: str, request: Request, db: DbDep) -> JSONResponse:
    dep, secret = await run_in_threadpool(_secret_or_401, db, token, "teams", request)
    raw = await request.body()
    if len(raw) > 50_000 or not svc.verify_teams(
        secret, request.headers.get("authorization", ""), raw
    ):
        raise AppError(401, "팀즈에서 온 요청인지 확인하지 못했어요.", "보안 토큰을 확인하세요.")
    _check_app_limit(dep)
    closed = _closed_message(dep)
    if closed:
        return JSONResponse({"type": "message", "text": closed})
    if _duplicate(raw):
        return JSONResponse({"type": "message", "text": "이미 찾아보는 중이에요."})
    try:
        activity = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise AppError(
            422, "요청을 읽지 못했어요.", "팀즈 나가는 웹훅 설정을 확인하세요."
        ) from None
    question = svc.clean_question(str(activity.get("text", "")))
    if not question:
        return JSONResponse({"type": "message", "text": "궁금한 것을 함께 적어 주세요."})
    sender = (activity.get("from") or {}).get("id", "")
    conv = (activity.get("conversation") or {}).get("id", "")
    session = svc.session_key("teams", secret, f"{conv}:{sender}")
    text = await run_in_threadpool(_answer, dep.id, session, question)
    return JSONResponse({"type": "message", "text": text})
