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
    """실행 중 AI 단계가 흘려보내는 답 조각을 받는 곳. 테스트는 가짜로 바꿔 끼운다."""

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
                cite: dict[str, Any] = {
                    "index": len(out) + 1,
                    "filename": r.get("filename", ""),
                    "content": str(r.get("content", ""))[:500],
                    "score": r.get("score"),
                }
                img = r.get("image")
                if isinstance(img, dict) and img.get("file_id"):
                    # v0.9 이미지 색인: 그림 조각이면 썸네일을 보여 줄 수 있게 참조를 싣는다
                    cite["image"] = {k: img.get(k) for k in ("file_id", "caption", "page", "kb_id")}
                out.append(cite)
    return out[:8]


def _cites_for_client(
    db: Session, conv: Conversation, cites: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """보낼 인용: 그림이 있고 누구나 열 수 있는 배포의 대화라면 24시간 서명 주소(image.url)를 붙인다."""
    if not any(isinstance(c.get("image"), dict) for c in cites) or not conv.deployment_id:
        return cites
    from api.services.kb_images import with_image_urls

    dep = db.get(Deployment, conv.deployment_id)
    token = dep.public_token if dep is not None and dep.access == "public" else None
    return with_image_urls(cites, token)


def follow_up_questions(db: Session, workspace_id: str, question: str, answer: str) -> list[str]:
    try:
        llm = resolve_llm(db, workspace_id, "default")
        db.rollback()  # 연결 반납: 아래 AI 호출 동안 DB 연결을 붙잡지 않는다
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
    """이벤트를 차례로 돌려준다. 호출자는 SSE로 보내거나(공개 챗) 모아서 JSON으로 돌려준다(서비스 API).

    DB 세션 안에서는 읽고 저장만 한다. 이벤트를 내보내는 동안(받는 쪽이 느릴 수 있음)과
    AI 호출 동안에는 DB 연결을 붙잡지 않는다(동시 사용자 한계, docs/loadtest-2026-11-03.md).
    """
    started = time.time()
    early: list[Event] | None = None  # 흐름을 돌리지 않고 바로 끝나는 경우
    run_id = ""
    stream_deltas = False
    with SessionLocal() as db:
        app = db.get(App, req_app_id)
        version = db.get(WorkflowVersion, version_id) if version_id else None
        conv = db.get(Conversation, conv_id)
        graph = version.graph if version is not None else draft_graph
        if app is None or graph is None or conv is None:
            early = [("error", {"message": "앱을 찾을 수 없어요.", "hint": "링크를 확인하세요."})]
        else:
            early = _handoff_events(db, app, conv, message, started)
            if early is None:
                early = _answer_without_run(db, app, conv, message, started)
            if early is None:
                run_id, stream_deltas = _start_run(
                    db, app, version, conv, graph, inputs, message, files, trigger, user_id
                )
    if early is not None:
        yield from early
        return
    yield ("status", {"message": "답을 만들고 있어요"})
    # 구독을 먼저 해야 실행이 바로 끝나도 조각을 놓치지 않는다
    source = open_delta_source(run_id) if stream_deltas else _NoDeltas()
    try:
        yield from _wait_for_answer(
            source, run_id, conv_id, req_app_id, message, started, stream_deltas
        )
    finally:
        source.close()


def _save_reply(db: Session, conv_id: str, text: str, started: float, **extra: Any) -> Message:
    m = Message(
        conversation_id=conv_id,
        role="assistant",
        content=text,
        latency_ms=int((time.time() - started) * 1000),
        **extra,
    )
    db.add(m)
    db.commit()
    from api.services.queue import enqueue_summary

    enqueue_summary(conv_id)
    return m


def wants_handoff(features: dict[str, Any], message: str) -> bool:
    cfg = features.get("handoff") or {}
    if not cfg.get("enabled") or not message:
        return False
    text = message.replace(" ", "")
    return any(str(k).replace(" ", "") in text for k in cfg.get("keywords") or [] if str(k).strip())


def start_handoff(db: Session, app: App, conv: Conversation, started: float) -> Message:
    """대화를 상담원에게 넘긴다: 상태를 바꾸고 안내 답을 남긴다."""
    features = merged_features(app.features)
    msg = str((features.get("handoff") or {}).get("message") or "상담원을 연결해 드릴게요.")
    conv.status = "handoff"
    m = _save_reply(db, conv.id, msg, started)
    from api.core.audit import audit

    audit(
        db,
        workspace_id=app.workspace_id,
        user_id=None,
        action="conversation.handoff",
        target_type="conversation",
        target_id=conv.id,
    )
    db.commit()
    return m


def _handoff_events(
    db: Session, app: App, conv: Conversation, message: str, started: float
) -> list[Event] | None:
    """상담원 전환 중이면 봇은 답하지 않는다(받은 말은 이미 저장돼 상담원이 본다)."""
    done_base = {"session_id": conv.external_session_id, "run_id": None}
    if conv.status == "handoff":
        return [
            ("handoff", {"message": "상담원에게 전달했어요. 답이 오면 여기에 보여 드릴게요."}),
            ("done", {**done_base, "status": "handoff", "message_id": None}),
        ]
    features = merged_features(app.features)
    if wants_handoff(features, message):
        m = start_handoff(db, app, conv, started)
        return [
            ("handoff", {"message": m.content, "message_id": m.id}),
            ("done", {**done_base, "status": "handoff", "message_id": m.id}),
        ]
    return None


def _answer_without_run(
    db: Session, app: App, conv: Conversation, message: str, started: float
) -> list[Event] | None:
    """입력 검열·주석 답변으로 바로 답할 수 있으면 보낼 이벤트를, 아니면 None."""
    features = merged_features(app.features)
    mod = features["moderation"]
    # 1) 입력 검열
    if mod["enabled"] and moderated(message, mod["keywords"]):
        m = _save_reply(db, conv.id, mod["preset_reply"], started, moderated=True)
        return [
            ("moderated", {"text": m.content, "message_id": m.id}),
            (
                "done",
                {
                    "session_id": conv.external_session_id,
                    "run_id": None,
                    "status": "moderated",
                    "message_id": m.id,
                },
            ),
        ]
    # 2) 주석 답변
    ann_cfg = features["annotation_reply"]
    if ann_cfg["enabled"] and message:
        hit = match_annotation(db, app.id, message, float(ann_cfg["score_threshold"]))
        if hit is not None:
            ann, _score = hit
            ann.hit_count = (ann.hit_count or 0) + 1
            m = _save_reply(db, conv.id, ann.answer, started, annotation_id=ann.id)
            return [
                ("annotated", {"text": ann.answer, "annotation_id": ann.id, "message_id": m.id}),
                (
                    "done",
                    {
                        "session_id": conv.external_session_id,
                        "run_id": None,
                        "status": "annotated",
                        "message_id": m.id,
                    },
                ),
            ]
    return None


def _start_run(
    db: Session,
    app: App,
    version: WorkflowVersion | None,
    conv: Conversation,
    graph: dict[str, Any],
    inputs: dict[str, Any],
    message: str,
    files: list[str],
    trigger: str,
    user_id: str | None,
) -> tuple[str, bool]:
    """3) 대화 기록을 붙여 실행을 만든다. (run_id, 답 조각을 보낼지) 반환."""
    features = merged_features(app.features)
    fields = input_fields(graph)
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
    from api.services.memory import history_text

    run_input["history"] = history_text(conv, prior) if window else ""
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
    mod = features["moderation"]
    # 출력 검열을 켠 앱은 검열 전 글이 보이지 않도록 조각을 보내지 않는다
    return run.id, not (mod["enabled"] and mod["check_output"])


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
                # 다른 AI 단계가 시작됨 → 지금까지 보여 준 조각을 지운다
                yield ("delta_reset", {})
            last_node = node_id
            yield ("delta", {"text": str(d.get("text", "")), "node_id": node_id})
        wait = POLL_SECONDS
        with SessionLocal() as db:
            outcome = _check_run(db, run_id, conv_id, req_app_id, started)
        if outcome is None:
            continue  # 아직 실행 중
        status, events_out, follow, done = outcome
        yield from events_out
        if follow is not None:
            # 이어질 질문은 AI 호출이라 몇 초 걸린다. DB 연결 없이 한다.
            with SessionLocal() as fdb:
                qs = follow_up_questions(fdb, follow[0], message, follow[1])
            if qs:
                yield ("suggestions", qs)
        if done is not None:
            yield done
            return
        break  # 답을 만들지 못함 → 아래에서 done
    else:
        yield (
            "error",
            {"message": "답이 너무 오래 걸려요.", "hint": "잠시 후 다시 물어봐 주세요."},
        )
    with SessionLocal() as db:
        conv = db.get(Conversation, conv_id)
        sid = conv.external_session_id if conv else None
    yield ("done", {"session_id": sid, "run_id": run_id, "status": status, "message_id": None})


def _check_run(
    db: Session, run_id: str, conv_id: str, req_app_id: str, started: float
) -> tuple[str, list[Event], tuple[str, str] | None, Event | None] | None:
    """실행이 끝났으면 답을 저장하고 (상태, 보낼 이벤트, 이어질 질문 재료, done)을, 아니면 None."""
    r = db.get(Run, run_id)
    status = r.status if r else "failed"
    app = db.get(App, req_app_id)
    conv = db.get(Conversation, conv_id)
    if app is None or conv is None:
        return (
            status,
            [("error", {"message": "앱이나 대화가 사라졌어요.", "hint": "화면을 새로고침하세요."})],
            None,
            None,
        )
    if r is None or status not in ("succeeded", "failed", "waiting_approval"):
        return None
    features = merged_features(app.features)
    if isinstance((r.output or {}).get("conv"), dict):
        conv.variables = dict(r.output["conv"])  # type: ignore[index]
    if status == "succeeded":
        answer = str((r.output or {}).get("text", "")) or "(답이 비어 있어요)"
    elif status == "waiting_approval":
        kind = str((r.approval or {}).get("kind") or "approval")
        answer = (
            "담당자의 승인을 기다리고 있어요. 결과가 나오면 이 대화에 알려 드릴게요."
            if kind == "approval"
            else "담당자의 확인을 기다리고 있어요. 끝나면 이 대화에 결과를 알려 드릴게요."
        )
    else:
        answer = ""
    if not answer:
        db.commit()
        return (
            status,
            [
                (
                    "error",
                    {
                        "message": "답을 만들지 못했어요.",
                        "hint": "잠시 후 다시 물어보거나 앱 관리자에게 알려 주세요.",
                    },
                )
            ],
            None,
            None,
        )
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
    m = _save_reply(
        db,
        conv.id,
        answer,
        started,
        run_id=run_id,
        moderated=was_moderated,
        citations=cites or None,
    )
    payload: dict[str, Any] = {"text": answer, "message_id": m.id}
    if status == "succeeded" and not was_moderated:
        # v0.9: 이미지·파일 단계가 만든 파일은 서명된 내려받기 링크와 함께 답에 실어 보낸다
        from api.services import run_files

        made = run_files.files_of_run(db, r, app.workspace_id)
        if made:
            payload["files"] = run_files.with_public_links(made, app.id, run_id)
    events_out: list[Event] = [("moderated" if was_moderated else "answer", payload)]
    if cites:
        events_out.append(("citations", _cites_for_client(db, conv, cites)))
    if status == "waiting_approval":
        # 챗 화면은 이 신호를 받으면 지난 메시지를 주기적으로 다시 읽어 늦게 온 결과를 보여 준다
        events_out.append(("pending", {"run_id": run_id, "message": answer}))
    follow = (
        (app.workspace_id, answer)
        if features["follow_up"]["enabled"] and status == "succeeded" and not was_moderated
        else None
    )
    done: Event = (
        "done",
        {
            "session_id": conv.external_session_id,
            "run_id": run_id,
            "status": status,
            "message_id": m.id,
        },
    )
    return status, events_out, follow, done
