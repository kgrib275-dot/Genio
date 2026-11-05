"""작업본 번호·기록(v0.9). 앱의 draft_graph가 바뀌어 저장될 때마다 어디서 바꿨든 한곳에서 처리한다.

- apps.draft_rev를 1 올리고 마지막으로 고친 사람(updated_by)을 적는다.
- 바뀐 뒤의 흐름을 draft_snapshots에 쌓는다(앱마다 최근 20번). 바뀌기 전 번호의 기록이 없으면 함께 남겨
  '내가 불러온 시점'을 나중에 되살릴 수 있게 한다.
- 커밋이 끝난 뒤에만 같은 앱을 연 사람들에게 draft_changed 알림을 보낸다(롤백하면 보내지 않는다).
사용자는 session.info["actor_id"], 화면 구분은 session.info["client_id"]에서 읽는다(deps.py가 채운다).
"""

import logging
from typing import Any

from sqlalchemy import delete, event, func, inspect, select
from sqlalchemy.orm import Session

from api.models.entities import App, DraftSnapshot

log = logging.getLogger("genio.draft")
KEEP_SNAPSHOTS = 20
EVENTS_KEY = "draft_events"


def _has_snapshot(session: Session, app_id: str, rev: int) -> bool:
    n = session.scalar(
        select(func.count())
        .select_from(DraftSnapshot)
        .where(DraftSnapshot.app_id == app_id, DraftSnapshot.rev == rev)
    )
    return bool(n)


@event.listens_for(Session, "before_flush")
def _bump_draft_rev(session: Session, _ctx: Any, _instances: Any) -> None:
    actor = session.info.get("actor_id")
    for obj in list(session.dirty):
        if not isinstance(obj, App):
            continue
        hist = inspect(obj).attrs.draft_graph.history
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = obj.draft_graph
        if old == new:  # 같은 내용을 다시 저장한 것은 번호를 올리지 않는다
            continue
        old_rev = int(obj.draft_rev or 0)
        rev = old_rev + 1
        obj.draft_rev = rev
        obj.updated_by = actor
        if old and not _has_snapshot(session, obj.id, old_rev):
            session.add(DraftSnapshot(app_id=obj.id, rev=old_rev, graph=old, user_id=None))
        session.add(DraftSnapshot(app_id=obj.id, rev=rev, graph=new or {}, user_id=actor))
        session.execute(
            delete(DraftSnapshot).where(
                DraftSnapshot.app_id == obj.id, DraftSnapshot.rev <= rev - KEEP_SNAPSHOTS
            )
        )
        session.info.setdefault(EVENTS_KEY, []).append(
            {
                "app_id": obj.id,
                "rev": rev,
                "user_id": actor,
                "client_id": session.info.get("client_id"),
            }
        )


@event.listens_for(Session, "after_commit")
def _publish_draft_events(session: Session) -> None:
    pending = session.info.pop(EVENTS_KEY, None)
    if not pending:
        return
    try:
        from api.engine import app_bus

        for ev in pending:
            app_bus.publish(
                ev["app_id"],
                "draft_changed",
                {k: ev[k] for k in ("rev", "user_id", "client_id")},
            )
    except Exception:
        log.exception("작업본 변경 알림 실패")


@event.listens_for(Session, "after_soft_rollback")
def _drop_draft_events(session: Session, _prev: Any) -> None:
    session.info.pop(EVENTS_KEY, None)
