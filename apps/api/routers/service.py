"""서비스 API(앱 API 키 인증): 채팅 메시지, 흐름 실행, 파라미터. 다른 시스템이 Genio 앱을 부를 때 쓴다."""

import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.errors import AppError
from api.db import SessionLocal
from api.deps import DbDep
from api.models import App, AppApiKey, Run, WorkflowVersion
from api.routers.apps_v02 import hash_key
from api.routers.common import client_ip
from api.services import apps as app_svc
from api.services.app_config import merged_features
from api.services.chat import ChatRequest, input_fields, run_chat, start_chat
from api.services.queue import enqueue_run

router = APIRouter(prefix="/service", tags=["service-api"])
SERVICE_RATE_PER_MINUTE = 60
RUN_WAIT_SECONDS = 120


class AppKeyCtx:
    def __init__(self, app: App, version: WorkflowVersion, key: AppApiKey) -> None:
        self.app = app
        self.version = version
        self.key = key


def app_key(request: Request, db: DbDep) -> AppKeyCtx:
    auth = request.headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not raw.startswith("gk-"):
        raise AppError(
            401, "앱 API 키가 필요해요.", "헤더에 Authorization: Bearer gk-... 를 넣어 주세요."
        )
    key = db.scalar(select(AppApiKey).where(AppApiKey.key_hash == hash_key(raw)))
    if key is None:
        raise AppError(
            401, "앱 API 키가 올바르지 않아요.", "앱의 API 화면에서 키를 확인하거나 새로 만드세요."
        )
    if not ratelimit.allow(f"svc:{key.id}:{client_ip(request)}", SERVICE_RATE_PER_MINUTE):
        raise AppError(429, "요청이 너무 많아요.", "1분 뒤에 다시 시도하세요(분당 60회).")
    app = db.get(App, key.app_id)
    version = app_svc.latest_version(db, key.app_id) if app else None
    if app is None or version is None:
        raise AppError(409, "앱에 저장된 버전이 없어요.", "빌더에서 '버전 저장'을 먼저 하세요.")
    key.last_used_at = datetime.now(UTC)
    db.commit()
    return AppKeyCtx(app, version, key)


KeyDep = Annotated[AppKeyCtx, Depends(app_key)]


@router.get("/parameters")
def parameters(k: KeyDep) -> dict[str, Any]:
    f = merged_features(k.app.features)
    return {
        "app": {"name": k.app.name, "type": k.app.type, "description": k.app.description},
        "version": k.version.version,
        "input_fields": input_fields(k.version.graph),
        "features": {
            "opening_statement": f["opening_statement"],
            "suggested_questions": f["suggested_questions"],
        },
    }


class ChatMessageIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    inputs: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, max_length=100)
    user: str | None = Field(default=None, max_length=100)


@router.post("/chat-messages")
def chat_messages(body: ChatMessageIn, k: KeyDep, db: DbDep) -> dict[str, Any]:
    req = ChatRequest(
        app=k.app,
        version=k.version,
        deployment=None,
        user_id=None,
        message=body.query,
        session_id=body.conversation_id,
        inputs=body.inputs,
    )
    conv, _ = start_chat(db, req)
    answer, message_id, citations, status, run_id = "", None, [], "failed", None
    for name, data in run_chat(
        conv.id, k.app.id, k.version.id, None, body.query, body.inputs, [], trigger="api"
    ):
        if name in ("answer", "moderated", "annotated") and isinstance(data, dict):
            answer, message_id = str(data.get("text", "")), data.get("message_id")
        elif name == "citations" and isinstance(data, list):
            citations = data
        elif name == "error" and isinstance(data, dict):
            raise AppError(502, str(data.get("message")), str(data.get("hint")))
        elif name == "done" and isinstance(data, dict):
            status, run_id = str(data.get("status")), data.get("run_id")
    usage = _usage(db, run_id)
    return {
        "answer": answer,
        "conversation_id": conv.external_session_id,
        "message_id": message_id,
        "metadata": {"status": status, "run_id": run_id, "usage": usage, "citations": citations},
    }


def _usage(db: Session, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    with SessionLocal() as s:
        r = s.get(Run, run_id)
        u = (r.token_usage if r else None) or {}
        return {
            "input_tokens": u.get("input_tokens", 0),
            "output_tokens": u.get("output_tokens", 0),
            "cost": float(r.cost or 0) if r else 0.0,
        }


class WorkflowRunIn(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.post("/workflows/run")
def workflows_run(body: WorkflowRunIn, k: KeyDep, db: DbDep) -> dict[str, Any]:
    started = time.time()
    run = Run(app_id=k.app.id, version_id=k.version.id, trigger="api", input=body.inputs)
    db.add(run)
    db.commit()
    run_id = run.id
    enqueue_run(run_id)
    deadline = time.time() + RUN_WAIT_SECONDS
    while time.time() < deadline:
        with SessionLocal() as s:
            r = s.get(Run, run_id)
            if r is not None and r.status in ("succeeded", "failed", "waiting_approval"):
                return {
                    "run_id": run_id,
                    "status": r.status,
                    "outputs": r.output or {},
                    "error": r.error,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
        time.sleep(0.3)
    return {
        "run_id": run_id,
        "status": "running",
        "outputs": {},
        "error": None,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
