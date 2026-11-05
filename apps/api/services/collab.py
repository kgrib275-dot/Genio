"""동시 편집·댓글 서비스(v0.9): 작업본 기록 조회, 충돌 응답, 댓글 직렬화·언급 처리."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.audit import audit
from api.models import App, CanvasComment, DraftSnapshot, Membership, User

log = logging.getLogger("genio.collab")
MENTION_ROLES = ("owner", "admin", "builder", "operator")  # 빌더를 열 수 있는 역할


def snapshot_graph(db: Session, app_id: str, rev: int) -> dict[str, Any] | None:
    """rev 번호 때의 작업본(최근 20번까지). 없으면 None."""
    row = db.scalar(
        select(DraftSnapshot).where(DraftSnapshot.app_id == app_id, DraftSnapshot.rev == rev)
    )
    return dict(row.graph or {}) if row is not None else None


def conflict_body(
    *,
    rev: int,
    base: dict[str, Any] | None,
    mine: dict[str, Any],
    theirs: dict[str, Any],
    merged: dict[str, Any],
    conflicts: list[dict[str, Any]],
    stale: bool = False,
) -> dict[str, Any]:
    """409 응답 본문. 화면이 '충돌 해결' 창을 그리는 데 쓴다(두 줄 문구는 그대로 포함)."""
    if stale:
        message = "내가 연 뒤로 흐름이 많이 바뀌어 자동으로 합칠 수 없어요."
        hint = "상대가 저장한 흐름을 새로 불러오거나, 내 것으로 덮어쓸 수 있어요."
    else:
        message = "다른 사람이 같은 곳을 먼저 고쳤어요."
        hint = "겹치는 항목마다 내 것과 상대 것 중 하나를 골라 주세요."
    return {
        "detail": {
            "message": message,
            "hint": hint,
            "conflict": {
                "rev": rev,
                "stale": stale,
                "base": base,
                "mine": mine,
                "theirs": theirs,
                "merged": merged,
                "conflicts": conflicts,
            },
        }
    }


# ---------------- 댓글 ----------------
def _names(db: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))}


def comment_dicts(db: Session, rows: list[CanvasComment]) -> list[dict[str, Any]]:
    """모든 댓글(뿌리+답글)을 스레드 목록으로: 뿌리마다 replies가 붙는다."""
    ids: set[str] = set()
    for c in rows:
        ids.update(c.mentions or [])
        for uid in (c.created_by, c.resolved_by):
            if uid:
                ids.add(uid)
    names = _names(db, ids)

    def one(c: CanvasComment) -> dict[str, Any]:
        return {
            "id": c.id,
            "node_id": c.node_id,
            "x": c.x,
            "y": c.y,
            "parent_id": c.parent_id,
            "body": c.body,
            "mentions": [
                {"id": m, "name": names.get(m, "(탈퇴한 사람)")} for m in c.mentions or []
            ],
            "resolved": bool(c.resolved),
            "resolved_by": names.get(c.resolved_by or "") if c.resolved_by else None,
            "author": {
                "id": c.created_by,
                "name": names.get(c.created_by or "", "(탈퇴한 사람)"),
            },
            "created_at": c.created_at,
            "edited_at": c.edited_at,
        }

    roots = [c for c in rows if c.parent_id is None]
    roots.sort(key=lambda c: c.created_at)
    replies: dict[str, list[CanvasComment]] = {}
    for c in rows:
        if c.parent_id:
            replies.setdefault(c.parent_id, []).append(c)
    out = []
    for r in roots:
        d = one(r)
        d["replies"] = [one(x) for x in sorted(replies.get(r.id, []), key=lambda c: c.created_at)]
        out.append(d)
    return out


def valid_mentions(db: Session, workspace_id: str, user_ids: list[str]) -> list[str]:
    """언급한 사람 중 이 워크스페이스에서 빌더를 열 수 있는 사람만(중복 제거, 최대 10명)."""
    wanted = list(dict.fromkeys(str(u) for u in user_ids))[:10]
    if not wanted:
        return []
    ok = set(
        db.scalars(
            select(Membership.user_id).where(
                Membership.workspace_id == workspace_id,
                Membership.user_id.in_(wanted),
                Membership.role.in_(MENTION_ROLES),
            )
        )
    )
    return [u for u in wanted if u in ok]


def notify_mentions(
    db: Session,
    *,
    app: App,
    comment: CanvasComment,
    author: User,
    new_ids: list[str],
    link: str,
) -> None:
    """언급된 사람에게: 활동 기록(comment.mention) + 시스템 메일이 설정돼 있으면 메일(실패해도 조용히)."""
    from api.services import mailer

    targets = [u for u in new_ids if u != author.id]
    if not targets:
        return
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(targets)))}
    for uid in targets:
        audit(
            db,
            workspace_id=app.workspace_id,
            user_id=author.id,
            action="comment.mention",
            target_type="user",
            target_id=uid,
            meta={"app_id": app.id, "comment_id": comment.id},
        )
    try:
        if not mailer.configured(db):
            return
        for uid in targets:
            user = users.get(uid)
            if user is None or not user.email:
                continue
            if not ratelimit.allow(f"commentmail:{author.id}", 10, 60):
                break
            excerpt = " ".join(comment.body.split())[:200]
            mailer.send(
                db,
                user.email,
                f"[Genio] {author.name}님이 '{app.name}' 앱 댓글에서 회원님을 언급했어요",
                f"{author.name}님이 '{app.name}' 앱의 댓글에서 회원님을 언급했어요.\n\n"
                f"“{excerpt}”\n\n열기: {link}\n",
            )
    except Exception:
        log.warning("댓글 언급 메일을 보내지 못했어요(app=%s)", app.id)
