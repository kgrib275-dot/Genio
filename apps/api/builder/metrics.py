"""대화형 빌더 측정 지표(기능 정의서 S1).

- 첫 요청에서 동작하는 앱(검증 통과)까지 걸린 시간: first_request_at → first_valid_at
- 수정 대화 횟수: 검증을 한 번 통과한 뒤의 사용자 메시지 수(edit_turns)
- 사람이 캔버스를 직접 만진 비율: canvas_edits / (canvas_edits + builder_ops)

값은 builder_sessions.metrics(JSON)에 쌓는다. JSON 열은 통째로 다시 넣어야 바뀐 것으로 저장된다.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import App, BuilderSession


def _now() -> datetime:
    return datetime.now(UTC)


def _get(sess: BuilderSession) -> dict[str, Any]:
    return dict(sess.metrics or {})


def on_user_turn(sess: BuilderSession) -> None:
    m = _get(sess)
    m.setdefault("first_request_at", _now().isoformat())
    m["user_turns"] = int(m.get("user_turns", 0)) + 1
    if m.get("first_valid_at"):
        m["edit_turns"] = int(m.get("edit_turns", 0)) + 1
    sess.metrics = m


def on_builder_ops(sess: BuilderSession, count: int) -> None:
    if count <= 0:
        return
    m = _get(sess)
    m["builder_ops"] = int(m.get("builder_ops", 0)) + count
    sess.metrics = m


def on_validate_ok(sess: BuilderSession) -> None:
    m = _get(sess)
    if m.get("first_valid_at"):
        return
    now = _now()
    m["first_valid_at"] = now.isoformat()
    started = m.get("first_request_at")
    if started:
        try:
            first = datetime.fromisoformat(str(started))
            m["seconds_to_valid"] = round(max(0.0, (now - first).total_seconds()), 1)
        except ValueError:
            pass
    sess.metrics = m


def on_canvas_edit(db: Session, app_id: str) -> None:
    """사람이 캔버스에서 고쳐 저장했을 때. 이 앱의 가장 최근 빌더 대화에 센다(대화가 없으면 무시)."""
    sess = db.scalar(
        select(BuilderSession)
        .where(BuilderSession.app_id == app_id)
        .order_by(BuilderSession.created_at.desc())
        .limit(1)
    )
    if sess is None:
        return
    m = _get(sess)
    m["canvas_edits"] = int(m.get("canvas_edits", 0)) + 1
    sess.metrics = m


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def workspace_metrics(db: Session, workspace_id: str) -> dict[str, Any]:
    rows = db.execute(
        select(BuilderSession, App.name, App.id)
        .join(App, App.id == BuilderSession.app_id)
        .where(App.workspace_id == workspace_id)
    ).all()
    per_app: dict[str, dict[str, Any]] = {}
    to_valid: list[float] = []
    edit_turns: list[float] = []
    user_turns: list[float] = []
    canvas = ops = 0
    for sess, app_name, app_id in rows:
        m = sess.metrics or {}
        if not m.get("user_turns"):
            continue
        a = per_app.setdefault(
            app_id,
            {
                "app_id": app_id,
                "app_name": app_name,
                "sessions": 0,
                "seconds_to_valid": None,
                "user_turns": 0,
                "edit_turns": 0,
                "canvas_edits": 0,
                "builder_ops": 0,
            },
        )
        a["sessions"] += 1
        a["user_turns"] += int(m.get("user_turns", 0))
        a["edit_turns"] += int(m.get("edit_turns", 0))
        a["canvas_edits"] += int(m.get("canvas_edits", 0))
        a["builder_ops"] += int(m.get("builder_ops", 0))
        if m.get("seconds_to_valid") is not None:
            sec = float(m["seconds_to_valid"])
            to_valid.append(sec)
            prev = a["seconds_to_valid"]
            a["seconds_to_valid"] = sec if prev is None else min(prev, sec)
        user_turns.append(float(m.get("user_turns", 0)))
        edit_turns.append(float(m.get("edit_turns", 0)))
        canvas += int(m.get("canvas_edits", 0))
        ops += int(m.get("builder_ops", 0))
    apps = sorted(per_app.values(), key=lambda x: x["user_turns"], reverse=True)
    for a in apps:
        total = a["canvas_edits"] + a["builder_ops"]
        a["manual_ratio"] = round(a["canvas_edits"] / total, 3) if total else None
    return {
        "sessions": len(user_turns),
        "sessions_valid": len(to_valid),
        "avg_seconds_to_valid": _avg(to_valid),
        "avg_user_turns": _avg(user_turns),
        "avg_edit_turns": _avg(edit_turns),
        "manual_ratio": round(canvas / (canvas + ops), 3) if (canvas + ops) else None,
        "apps": apps[:50],
    }
