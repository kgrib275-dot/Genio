"""챗 실행(공개 챗 SSE·서비스 API 공용): 검열 → 주석 답변 → 흐름 실행 → 출력 검열 → 출처 → 이어서 물을 질문."""

import contextlib
import difflib
import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.security import random_token
from api.db import SessionLocal
from api.engine import events
from api.llm.base import LlmError
from api.llm.registry import resolve_llm
from api.models import (
    Annotation,
    App,
    Conversation,
    Deployment,
    Message,
    Run,
    RunStep,
    WorkflowVersion,
)
from api.services.app_config import merged_features
from api.services.queue import enqueue_run

CHAT_WAIT_SECONDS = 120
Event = tuple[str, dict[str, Any] | list[Any]]
POLL_SECONDS = 0.3
# '대화로 시험하기' 대화는 세션 id가 이 글로 시작한다(로그·통계에서 뺀다)
PREVIEW_PREFIX = "preview:"


# ---------------- 답 조각(delta) 중계 ----------------
class DeltaSource(Protocol):
    """실행 중 AI 블록이 흘려보내는 답 조각을 받는 곳. 테스트는 가짜로 바꿔 끼운다."""

    def poll(self, timeout: float) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class _RedisDeltas:
    def __init__(self, pubsub: Any) -> None:
        self.pubsub = pubsub

    def poll(self, timeout: float) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                break
            try:
                msg = self.pubsub.get_message(timeout=remaining)
            except Exception:  # 알림이 끊겨도 DB 확인으로 계속한다
                break
            if msg is None:
                if out:
                    break
                continue
            try:
                data = json.loads(msg.get("data") or b"{}")
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("type") == "delta":
                out.append(data)
        return out

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.pubsub.close()


class _NoDeltas:
    def poll(self, timeout: float) -> list[dict[str, Any]]:
        time.sleep(timeout)
        return []

    def close(self) -> None:
        return None


def open_delta_source(run_id: str) -> DeltaSource:
    """Redis가 있으면 실행 채널을 구독하고, 없으면(테스트·로컬) 조각 없이 기다리기만 한다."""
    ps = events.subscriber(run_id)
    return _RedisDeltas(ps) if ps is not None else _NoDeltas()


def input_fields(graph: dict[str, Any]) -> list[dict[str, Any]]:
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


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def match_annotation(
    db: Session, app_id: str, question: str, threshold: float
) -> tuple[Annotation, float] | None:
    q = _norm(question)
    if not q:
        return None
    best: tuple[Annotation, float] | None = None
    for a in db.scalars(select(Annotation).where(Annotation.app_id == app_id)):
        score = difflib.SequenceMatcher(None, q, _norm(a.question)).ratio()
        if score >= threshold and (best is None or score > best[1]):
            best = (a, score)
    return best


def moderated(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k.strip() and k.strip().lower() in low for k in keywords)


def citations_from_steps(db: Session, run_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    steps = db.scalars(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq))
    for s in steps:
        results = (s.output or {}).get("results") if s.status == "succeeded" else None
        if not isinstance(results, list):
            continue
        for r in results:
            if isinstance(r, dict) and "chunk_id" in r:
                out.append(
                    {
                        "index": len(out) + 1,
                        "filename": r.get("filename", ""),
                        "content": str(r.get("content", ""))[:500],
                        "score": r.get("score"),
                    }
                )
    return out[:8]


def follow_up_questions(db: Session, workspace_id: str, question: str, answer: str) -> list[str]:
    try:
        llm = resolve_llm(db, workspace_id, "default")
        res = llm.adapter.complete(
            model=llm.model,
            system="사용자가 이어서 물어볼 만한 짧은 질문 3개를 한국어로 만드세요. 각 질문은 25자 이내.",
            prompt=f"질문: {question}\n답변: {answer[:1500]}",
            temperature=None,
            json_schema={
                "type": "object",
                "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
                "required": ["questions"],
            },
        )
    except LlmError:
        return []
    qs = (res.data or {}).get("questions") or []
    return [str(q).strip() for q in qs if str(q).strip()][:3]


@dataclass
class ChatRequest:
    app: App
    version: WorkflowVersion | None
    deployment: Deployment | None
    user_id: str | None
    message: str
    session_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    trigger: str = "chat"


def start_chat(db: Session, req: ChatRequest) -> tuple[Conversation, Message]:
    """대화를 찾거나 만들고 사용자 메시지를 저장한다."""
    conv: Conversation | None = None
    if req.session_id:
        q = select(Conversation).where(
            Conversation.app_id == req.app.id, Conversation.external_session_id == req.session_id
        )
        if req.deployment is not None:
            q = q.where(Conversation.deployment_id == req.deployment.id)
        conv = db.scalar(q)
    if conv is None:
        sid = req.session_id or random_token(12)
        if req.trigger == "preview" and not sid.startswith(PREVIEW_PREFIX):
            sid = PREVIEW_PREFIX + sid
        conv = Conversation(
            app_id=req.app.id,
            deployment_id=req.deployment.id if req.deployment else None,
            user_id=req.user_id,
            external_session_id=sid,
            variables={},
        )
        db.add(conv)
        db.flush()
    text = req.message or json.dumps(req.inputs, ensure_ascii=False)
    msg = Message(conversation_id=conv.id, role="user", content=text)
    db.add(msg)
    db.commit()
    return conv, msg


def run_chat(
    conv_id: str,
    req_app_id: str,
    version_id: str | None,
    user_id: str | None,
    message: str,
    inputs: dict[str, Any],
    files: list[str],
    trigger: str = "chat",
    draft_graph: dict[str, Any] | None = None,
) -> Iterator[Event]:
    """이벤트를 차례로 돌려준다. 호출자는 SSE로 보내거나(공개 챗) 모아서 JSON으로 돌려준다(서비스 API)."""
    started = time.time()
    with SessionLocal() as db:
        app = db.get(App, req_app_id)
        version = db.get(WorkflowVersion, version_id) if version_id else None
        conv = db.get(Conversation, conv_id)
        graph = version.graph if version is not None else draft_graph
        if app is None or graph is None or conv is None:
            yield ("error", {"message": "앱을 찾을 수 없어요.", "hint": "링크를 확인하세요."})
            return
        features = merged_features(app.features)
        fields = input_fields(graph)
        mod = features["moderation"]

        conv_key = conv.id

        def save(text: str, **extra: Any) -> Message:
            m = Message(
                conversation_id=conv_key,
                role="assistant",
                content=text,
                latency_ms=int((time.time() - started) * 1000),
                **extra,
            )
            db.add(m)
            db.commit()
            return m

        # 1) 입력 검열
        if mod["enabled"] and moderated(message, mod["keywords"]):
            m = save(mod["preset_reply"], moderated=True)
            yield ("moderated", {"text": m.content, "message_id": m.id})
            yield (
                "done",
                {
                    "session_id": conv.external_session_id,
                    "run_id": None,
                    "status": "moderated",
                    "message_id": m.id,
                },
            )
            return

        # 2) 주석 답변
        ann_cfg = features["annotation_reply"]
        if ann_cfg["enabled"] and message:
            hit = match_annotation(db, app.id, message, float(ann_cfg["score_threshold"]))
            if hit is not None:
                ann, _score = hit
                ann.hit_count = (ann.hit_count or 0) + 1
                m = save(ann.answer, annotation_id=ann.id)
                yield (
                    "annotated",
                    {"text": ann.answer, "annotation_id": ann.id, "message_id": m.id},
                )
                yield (
                    "done",
                    {
                        "session_id": conv.external_session_id,
                        "run_id": None,
                        "status": "annotated",
                        "message_id": m.id,
                    },
                )
                return

        # 3) 흐름 실행
        window = int(features["memory"]["window"])
        prior = list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(window * 2 + 1)
            )
        )[::-1][:-1]
        run_input: dict[str, Any] = dict(inputs)
        if fields and message:
            run_input.setdefault(str(fields[0]["key"]), message)
        file_field = next((f["key"] for f in fields if f["type"] == "file"), None)
        if files and file_field:
            run_input.setdefault(str(file_field), files[0] if len(files) == 1 else files)
        run_input["history"] = "\n".join(f"{m.role}: {m.content}" for m in prior) if window else ""
        run_input["__conv"] = dict(conv.variables or {})
        run = Run(
            app_id=app.id,
            version_id=version.id if version is not None else None,
            # 작업본(대화로 시험하기)은 그래프를 그대로 붙여 둔다
            graph_snapshot=None if version is not None else graph,
            trigger=trigger,
            input=run_input,
            created_by=user_id,
        )
        db.add(run)
        db.commit()
        run_id = run.id
        # 출력 검열을 켠 앱은 검열 전 글이 보이지 않도록 조각을 보내지 않는다
        stream_deltas = not (mod["enabled"] and mod["check_output"])
    yield ("status", {"message": "답을 만들고 있어요"})
    # 구독을 먼저 해야 실행이 바로 끝나도 조각을 놓치지 않는다
    source = open_delta_source(run_id) if stream_deltas else _NoDeltas()
    try:
        yield from _wait_for_answer(
            source, run_id, conv_id, req_app_id, message, started, stream_deltas
        )
    finally:
        source.close()


def _wait_for_answer(
    source: DeltaSource,
    run_id: str,
    conv_id: str,
    req_app_id: str,
    message: str,
    started: float,
    stream_deltas: bool,
) -> Iterator[Event]:
    enqueue_run(run_id)
    deadline = time.time() + CHAT_WAIT_SECONDS
    status = "queued"
    last_node: str | None = None
    wait = 0.05  # 처음엔 짧게(바로 끝난 실행을 기다리지 않게)
    while time.time() < deadline:
        # 답 조각을 먼저 흘려보내고(쌓인 것 포함) 그 다음 실행이 끝났는지 본다
        for d in source.poll(wait):
            if not stream_deltas:
                continue
            node_id = str(d.get("node_id") or "")
            if last_node is not None and node_id != last_node:
                # 다른 AI 블록이 시작됨 → 지금까지 보여 준 조각을 지운다
                yield ("delta_reset", {})
            last_node = node_id
            yield ("delta", {"text": str(d.get("text", "")), "node_id": node_id})
        wait = POLL_SECONDS
        with SessionLocal() as db:
            r = db.get(Run, run_id)
            status = r.status if r else "failed"
            app = db.get(App, req_app_id)
            conv = db.get(Conversation, conv_id)
            if app is None or conv is None:
                yield (
                    "error",
                    {"message": "앱이나 대화가 사라졌어요.", "hint": "화면을 새로고침하세요."},
                )
                return
            if r is not None and status in ("succeeded", "failed", "waiting_approval"):
                features = merged_features(app.features)
                if isinstance((r.output or {}).get("conv"), dict):
                    conv.variables = dict(r.output["conv"])  # type: ignore[index]
                if status == "succeeded":
                    answer = str((r.output or {}).get("text", "")) or "(답이 비어 있어요)"
                elif status == "waiting_approval":
                    answer = "담당자의 승인을 기다리고 있어요. 승인되면 처리돼요."
                else:
                    answer = ""
                if not answer:
                    db.commit()
                    yield (
                        "error",
                        {
                            "message": "답을 만들지 못했어요.",
                            "hint": "잠시 후 다시 물어보거나 앱 관리자에게 알려 주세요.",
                        },
                    )
                    break
                mod = features["moderation"]
                was_moderated = bool(
                    mod["enabled"] and mod["check_output"] and moderated(answer, mod["keywords"])
                )
                if was_moderated:
                    answer = mod["preset_reply"]
                cites = (
                    citations_from_steps(db, run_id)
                    if features["citations"]["enabled"] and not was_moderated
                    else []
                )
                m = Message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=answer,
                    run_id=run_id,
                    moderated=was_moderated,
                    citations=cites or None,
                    latency_ms=int((time.time() - started) * 1000),
                )
                db.add(m)
                db.commit()
                yield (
                    "moderated" if was_moderated else "answer",
                    {"text": answer, "message_id": m.id},
                )
                if cites:
                    yield ("citations", cites)
                if features["follow_up"]["enabled"] and status == "succeeded" and not was_moderated:
                    qs = follow_up_questions(db, app.workspace_id, message, answer)
                    if qs:
                        yield ("suggestions", qs)
                yield (
                    "done",
                    {
                        "session_id": conv.external_session_id,
                        "run_id": run_id,
                        "status": status,
                        "message_id": m.id,
                    },
                )
                return
    else:
        yield (
            "error",
            {"message": "답이 너무 오래 걸려요.", "hint": "잠시 후 다시 물어봐 주세요."},
        )
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        sid = conv.external_session_id if conv else None
    yield ("done", {"session_id": sid, "run_id": run_id, "status": status, "message_id": None})
