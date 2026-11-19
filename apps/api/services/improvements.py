"""개선이 필요한 질문 모음: 챗봇이 답을 못 했거나 '싫어요'를 받은 답을 모아 담당자가 바로 고치게 한다."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError, not_found
from api.models import Annotation, Conversation, Message
from api.services import pii

DISMISSED = "dismissed"
# 답을 못 찾았을 때 챗봇이 흔히 쓰는 말(데모·샘플·템플릿 문구 포함)
NO_ANSWER_HINTS = (
    "찾지 못했",
    "찾을 수 없",
    "알 수 없",
    "모르겠",
    "확인할 수 없",
    "담당자에게 문의",
    "담당 부서에 문의",
)


def _norm(q: str) -> str:
    return "".join(q.lower().split())[:200]


def _reason(m: Message) -> str | None:
    if m.feedback == "dislike":
        return "dislike"
    if m.moderated:
        return None
    if any(h in (m.content or "") for h in NO_ANSWER_HINTS):
        return "no_answer"
    return None


def list_items(db: Session, app_id: str, *, days: int = 30, limit: int = 50) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    convs = {c.id: c for c in db.scalars(select(Conversation).where(Conversation.app_id == app_id))}
    if not convs:
        return {"open_count": 0, "items": []}
    msgs = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id.in_(list(convs)), Message.created_at >= since)
            .order_by(Message.conversation_id, Message.created_at)
        )
    )
    last_user: dict[str, Message] = {}
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for m in msgs:
        if m.role == "user":
            last_user[m.conversation_id] = m
            continue
        if m.role != "assistant" or m.annotation_id is not None:
            continue
        reason = _reason(m)
        q = last_user.get(m.conversation_id)
        if reason is None or q is None:
            continue
        g = groups.setdefault(
            _norm(q.content),
            {
                "message_id": m.id,
                "question": q.content,
                "answer": m.content,
                "reason": reason,
                "comment": m.feedback_comment or "",
                "count": 0,
                "message_ids": [],
                "last_at": m.created_at,
            },
        )
        g["count"] += 1
        g["message_ids"].append(m.id)
        if reason == "dislike":
            g["reason"] = "dislike"
        if m.feedback_comment and not g["comment"]:
            g["comment"] = m.feedback_comment
        if m.created_at >= g["last_at"]:
            g["last_at"] = m.created_at
            g["message_id"], g["answer"] = m.id, m.content
    masked = pii.logs_masked(db, _ws(db, app_id))
    items = sorted(groups.values(), key=lambda g: (-g["count"], -g["last_at"].timestamp()))
    out = []
    for g in items[:limit]:
        row = dict(g)
        if masked:
            row["question"] = pii.mask(row["question"])
            row["answer"] = pii.mask(row["answer"])
            row["comment"] = pii.mask(row["comment"])
        out.append(row)
    return {"open_count": len(items), "items": out}


def _ws(db: Session, app_id: str) -> str:
    from api.models import App

    app = db.get(App, app_id)
    if app is None:
        raise not_found("앱")
    return app.workspace_id


def _message_for(db: Session, app_id: str, message_id: str) -> tuple[Message, Message]:
    m = db.get(Message, message_id)
    conv = db.get(Conversation, m.conversation_id) if m else None
    if m is None or conv is None or conv.app_id != app_id or m.role != "assistant":
        raise not_found("답변")
    q = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == m.conversation_id,
            Message.role == "user",
            Message.created_at <= m.created_at,
        )
        .order_by(Message.created_at.desc())
    )
    if q is None:
        raise AppError(404, "이 답변의 질문을 찾지 못했어요.", "대화 기록에서 직접 확인해 주세요.")
    return m, q


def _related_ids(db: Session, app_id: str, question: str) -> list[str]:
    """같은 질문으로 모인 답변 전부(한 번에 처리하려고)"""
    items = list_items(db, app_id, days=365, limit=500)["items"]
    key = _norm(question)
    for it in items:
        if _norm(it["question"]) == key:
            return list(it["message_ids"])
    return []


def answer_with(db: Session, app_id: str, message_id: str, answer: str, user_id: str) -> Annotation:
    """고친 답을 '모범 답변'으로 등록하고 같은 질문의 모음을 처리 완료로 표시한다."""
    m, q = _message_for(db, app_id, message_id)
    ann = Annotation(
        app_id=app_id, question=q.content.strip()[:2000], answer=answer.strip(), created_by=user_id
    )
    db.add(ann)
    db.flush()
    for mid in _related_ids(db, app_id, q.content) or [m.id]:
        row = db.get(Message, mid)
        if row is not None:
            row.annotation_id = ann.id
    m.annotation_id = ann.id
    return ann


def dismiss(db: Session, app_id: str, message_id: str) -> int:
    """'고칠 필요 없어요'로 모음에서 뺀다. 처리한 답변 수를 돌려준다."""
    m, q = _message_for(db, app_id, message_id)
    ids = _related_ids(db, app_id, q.content) or [m.id]
    for mid in ids:
        row = db.get(Message, mid)
        if row is not None:
            row.annotation_id = DISMISSED
    m.annotation_id = DISMISSED
    return len(ids)
