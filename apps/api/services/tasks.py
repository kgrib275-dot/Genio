"""사람에게 맡기는 일(승인·질문·배정, 기능 정의서 S7).

흐름이 사람을 기다리는 단계(approval, ask_person, assign_task)에 닿으면 실행은 waiting_approval로
멈추고 HumanTask가 하나 생긴다. 작업함이나 링크(/t/{token})에서 처리하면 결정이 run.approval에
기록되고 실행이 그 단계 다음부터 이어진다.

v0.9(ADR 0013): 담당자를 다른 사람·역할에게 **전달**할 수 있고, 기한이 지나면 정해 둔 대로
(자동 반려·승인·올리기·정해 둔 값으로 계속·'시간 초과' 길) 처리하며, 기한 전에 한 번 다시 알린다.
시간 초과로 끝난 일도 사람이 처리한 것과 똑같이 run.approval에 결정을 적고 실행을 이어 간다.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.audit import audit
from api.core.errors import AppError
from api.core.security import random_token
from api.models import App, HumanTask, Membership, Run, User
from api.services import notify

KINDS = ("approval", "question", "assignment")
ROLES = ("owner", "admin", "builder", "operator", "member")
ROLE_KO = {
    "owner": "소유자",
    "admin": "관리자",
    "builder": "제작자",
    "operator": "운영자",
    "member": "사용자",
}
SYSTEM_NAME = "시스템"
MAX_HISTORY = 50


def now() -> datetime:
    return datetime.now(UTC)


def create_for_wait(
    db: Session, run: Run, app: App, node_id: str, wait: dict[str, Any]
) -> tuple[HumanTask, list[str]]:
    """실행이 사람을 기다릴 때 할 일을 만들고 알림을 보낸다. (할 일, 알림 결과 문장들)."""
    kind = str(wait.get("kind") or "approval")
    if kind not in KINDS:
        kind = "approval"
    message = str(wait.get("message") or "")
    title = str(wait.get("title") or message or "확인이 필요해요")[:300]
    due_at = None
    try:
        hours = float(wait.get("due_hours") or 0)
        if hours > 0:
            due_at = now() + timedelta(hours=min(hours, 24 * 90))
    except (TypeError, ValueError):
        due_at = None
    roles = wait.get("approver_roles") or []
    mode = str(wait.get("on_timeout") or "none")
    rules: dict[str, Any] = {
        "on_timeout": mode,
        "escalate_to": str(wait.get("timeout_escalate_to") or "") or None,
        "default": dict(wait.get("timeout_default") or {}),
        "remind_before_hours": wait.get("remind_before_hours"),
        "hours": hours if due_at is not None else None,
        # 다시 알리기·전달 알림에 쓰는 받는 곳(연결 정보 id·받는 사람)
        "notify": dict(wait.get("notify") or {}),
        "reminded": False,
        "escalated": False,
    }
    task = HumanTask(
        workspace_id=app.workspace_id,
        app_id=app.id,
        run_id=run.id,
        node_id=node_id,
        kind=kind,
        title=title,
        detail=str(wait.get("detail") or (message if title != message else ""))[:5000],
        fields=list(wait.get("fields") or []),
        assignee_user_id=str(wait.get("assignee_user_id") or "") or None,
        assignee_role=(
            str(wait.get("assignee_role") or "") or (roles[0] if len(roles) == 1 else None)
        ),
        status="open",
        response={},
        token=random_token(24),
        due_at=due_at,
        rules=rules,
        history=[],
    )
    db.add(task)
    db.flush()
    sent = notify.send(
        db,
        app.workspace_id,
        dict(wait.get("notify") or {}),
        kind=kind,
        app_name=app.name,
        title=task.title,
        detail=task.detail,
        token=task.token,
    )
    return task, sent


def can_act(task: HumanTask, run: Run | None, user_id: str, role: str | None) -> bool:
    """로그인한 사람이 이 일을 처리할 수 있는지(링크로 처리하는 경우는 토큰이 곧 권한)."""
    if role is None:
        return False
    if role in ("owner", "admin"):
        return True
    if task.assignee_user_id:
        return task.assignee_user_id == user_id  # 전달받았거나 지정된 사람만(승인 포함)
    if task.kind == "approval":
        roles = ((run.approval or {}) if run else {}).get("approver_roles") or []
        if roles:
            return role in roles
        return role in ("builder", "operator")
    if task.assignee_role:
        return role == task.assignee_role
    return role in ("builder", "operator")


def _clean_response(task: HumanTask, values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    missing: list[str] = []
    for f in task.fields or []:
        key = str(f.get("key") or "")
        if not key:
            continue
        v = values.get(key)
        if isinstance(v, str):
            v = v.strip()[:5000]
        if f.get("type") == "number" and v not in (None, ""):
            try:
                v = float(v)
            except (TypeError, ValueError) as exc:
                raise AppError(
                    422,
                    f"'{f.get('label') or key}'에는 숫자를 넣어 주세요.",
                    "숫자만 입력하세요.",
                ) from exc
        if v in (None, "") and f.get("required", True):
            missing.append(str(f.get("label") or key))
        out[key] = v
    if missing:
        raise AppError(
            422, f"'{', '.join(missing)}' 칸을 채워 주세요.", "모든 필수 칸을 채운 뒤 보내세요."
        )
    return out


def complete(
    db: Session,
    task: HumanTask,
    *,
    approved: bool | None,
    values: dict[str, Any],
    comment: str,
    user: User | None,
    via: str,
) -> Run | None:
    """할 일을 끝내고, 기다리던 실행에 결정을 적는다. 이어서 실행할 Run을 돌려준다(호출자가 큐에 넣음)."""
    if task.status != "open":
        raise AppError(409, "이미 처리된 요청이에요.", "작업함을 새로고침해 확인하세요.")
    if task.kind == "approval" and approved is None:
        raise AppError(422, "승인할지 반려할지 골라 주세요.", "승인 또는 반려 버튼을 누르세요.")
    response = _clean_response(task, values) if task.kind == "question" else {}
    name = user.name if user else "링크로 처리한 사람"
    task.status = "done"
    task.response = {
        **response,
        **({"approved": approved} if approved is not None else {}),
        "comment": comment[:1000],
    }
    task.completed_at = now()
    task.completed_by = user.id if user else None
    run = db.get(Run, task.run_id) if task.run_id else None
    if (
        run is not None
        and run.status == "waiting_approval"
        and run.approval
        and str(run.approval.get("node_id") or "") in ("", task.node_id or "")
    ):
        decision: dict[str, Any] = {
            "comment": comment[:1000],
            "decided_by": user.id if user else None,
            "decided_by_name": name,
            "decided_at": now().isoformat(),
            "decided_via": via,
        }
        if task.kind == "approval":
            decision["approved"] = bool(approved)
        else:
            decision["completed"] = True
            decision["response"] = response
        run.approval = {**run.approval, **decision}
    app = db.get(App, task.app_id)
    action = {
        "approval": "run.approve" if approved else "run.reject",
        "question": "task.answer",
        "assignment": "task.complete",
    }[task.kind]
    audit(
        db,
        workspace_id=app.workspace_id if app else task.workspace_id,
        user_id=user.id if user else None,
        action=action,
        target_type="run" if task.kind == "approval" else "task",
        target_id=task.run_id if task.kind == "approval" else task.id,
        meta={"comment": comment[:200], "via": via},
    )
    db.commit()
    if run is None or run.status != "waiting_approval":
        return None
    # 병렬 갈래에서 지금 기다리는 단계의 일이 아니면 실행을 다시 깨우지 않는다
    return (
        run if str((run.approval or {}).get("node_id") or "") in ("", task.node_id or "") else None
    )


def cancel(db: Session, task: HumanTask, user: User) -> None:
    if task.status != "open":
        raise AppError(409, "이미 처리된 요청이에요.", "작업함을 새로고침해 확인하세요.")
    task.status = "cancelled"
    task.completed_at = now()
    task.completed_by = user.id
    run = db.get(Run, task.run_id) if task.run_id else None
    if run is not None and run.status == "waiting_approval":
        run.status = "failed"
        run.error = f"'{task.title}' 요청이 취소되어 흐름을 멈췄어요."
        run.finished_at = now()
    db.commit()


def task_dict(task: HumanTask, app_name: str = "", *, with_token: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": task.id,
        "app_id": task.app_id,
        "app_name": app_name,
        "run_id": task.run_id,
        "node_id": task.node_id,
        "kind": task.kind,
        "title": task.title,
        "detail": task.detail,
        "fields": task.fields or [],
        "assignee_user_id": task.assignee_user_id,
        "assignee_role": task.assignee_role,
        "status": task.status,
        "response": task.response or {},
        "due_at": task.due_at,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        # v0.9: 시간 초과 처리·전달 이력
        "timeout_mode": (task.rules or {}).get("on_timeout") or "none",
        "escalated": bool((task.rules or {}).get("escalated")),
        "overdue": bool(
            task.status == "open"
            and task.due_at is not None
            and (_aware(task.due_at) or now()) <= now()
        ),
        "history": list(task.history or []),
    }
    if with_token:
        out["link"] = notify.task_link(task.token)
    return out


# ---------------- v0.9: 전달 ----------------
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _is_member(db: Session, workspace_id: str, user_id: str) -> User | None:
    m = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
    )
    return db.get(User, user_id) if m is not None else None


def _notify_new_assignee(
    db: Session,
    task: HumanTask,
    app: App | None,
    to_user: User | None,
    to_role: str | None,
    note: str,
) -> list[str]:
    """전달받은 사람에게 알림. 일을 만들 때 정한 알림 연결 정보를 그대로 쓰고, 이메일은 받는 사람만 바꾼다."""
    base = dict((task.rules or {}).get("notify") or {})
    if not base or app is None:
        return []
    cfg: dict[str, Any] = {}
    email = base.get("email") or {}
    if email.get("credential_id"):
        if to_user is not None:
            to = [to_user.email]
        else:
            rows = db.scalars(
                select(User)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.workspace_id == task.workspace_id, Membership.role == to_role)
                .limit(20)
            )
            to = [u.email for u in rows]
        if to:
            cfg["email"] = {"credential_id": str(email["credential_id"]), "to": to}
    if base.get("slack"):
        cfg["slack"] = base["slack"]
    if not cfg:
        return []
    return notify.send(
        db,
        task.workspace_id,
        cfg,
        kind=task.kind,
        app_name=app.name,
        title=f"[전달받음] {task.title}"[:300],
        detail=(f"{note}\n" if note else "") + task.detail,
        token=task.token,
    )


def forward(
    db: Session,
    task: HumanTask,
    *,
    by: User | None,
    to_user_id: str | None = None,
    to_role: str | None = None,
    comment: str = "",
    via: str = "forward",
) -> None:
    """담당자를 다른 사람(워크스페이스 멤버) 또는 역할로 바꾼다. 이력과 활동 기록을 남기고 알린다."""
    if task.status != "open":
        raise AppError(409, "이미 처리된 요청이에요.", "작업함을 새로고침해 확인하세요.")
    if bool(to_user_id) == bool(to_role):
        raise AppError(
            422, "전달할 사람이나 역할을 하나만 골라 주세요.", "사람 또는 역할 중 하나를 고르세요."
        )
    target_user: User | None = None
    if to_user_id:
        target_user = _is_member(db, task.workspace_id, to_user_id)
        if target_user is None:
            raise AppError(
                422,
                "그 사람은 이 워크스페이스 멤버가 아니에요.",
                "목록에 있는 멤버를 고르세요.",
            )
        if task.assignee_user_id == to_user_id:
            raise AppError(409, "이미 그 사람이 담당자예요.", "다른 사람이나 역할을 고르세요.")
        task.assignee_user_id = to_user_id
        task.assignee_role = None
        to_label = target_user.name
    else:
        if to_role not in ROLES:
            raise AppError(
                422,
                "전달할 역할이 올바르지 않아요.",
                "소유자·관리자·제작자·운영자·사용자 중에서 고르세요.",
            )
        if task.assignee_role == to_role and not task.assignee_user_id:
            raise AppError(409, "이미 그 역할이 담당이에요.", "다른 사람이나 역할을 고르세요.")
        task.assignee_user_id = None
        task.assignee_role = to_role
        to_label = ROLE_KO[str(to_role)]
    run = db.get(Run, task.run_id) if task.run_id else None
    if (
        task.kind == "approval"
        and to_role
        and run is not None
        and run.status == "waiting_approval"
        and run.approval
        and str(run.approval.get("node_id") or "") in ("", task.node_id or "")
    ):
        run.approval = {**run.approval, "approver_roles": [to_role]}
    app = db.get(App, task.app_id)
    note = comment.strip()[:500]
    entry: dict[str, Any] = {
        "at": now().isoformat(),
        "via": via,
        "by_user_id": by.id if by else None,
        "by_name": by.name if by else SYSTEM_NAME,
        "to_user_id": to_user_id,
        "to_role": to_role,
        "to_name": to_label,
        "comment": note,
    }
    entry["notified"] = _notify_new_assignee(db, task, app, target_user, to_role, note)
    task.history = [*(task.history or []), entry][-MAX_HISTORY:]
    audit(
        db,
        workspace_id=app.workspace_id if app else task.workspace_id,
        user_id=by.id if by else None,
        action="task.forward" if via == "forward" else "task.escalate",
        target_type="task",
        target_id=task.id,
        meta={"to": to_label, "comment": note[:200], "via": via},
    )
    db.commit()


# ---------------- v0.9: 시간 초과·다시 알리기 ----------------
def _decision_base(comment: str, mode: str) -> dict[str, Any]:
    return {
        "comment": comment,
        "decided_by": None,
        "decided_by_name": SYSTEM_NAME,
        "decided_at": now().isoformat(),
        "decided_via": "timeout",
        "timed_out": True,
        "timeout_mode": mode,
    }


_TIMEOUT_TEXT = {
    "reject": "정해 둔 시간이 지나 자동으로 반려했어요.",
    "approve": "정해 둔 시간이 지나 자동으로 승인했어요.",
    "continue": "정해 둔 시간이 지나 정해 둔 값으로 이어 갔어요.",
    "branch": "정해 둔 시간이 지나 '시간 초과' 길로 보냈어요.",
}


def _finish_by_timeout(db: Session, task: HumanTask, mode: str) -> Run | None:
    """시간 초과로 일을 끝낸다. 사람이 처리한 것과 똑같이 run.approval에 결정을 적는다."""
    rules = task.rules or {}
    comment = _TIMEOUT_TEXT.get(mode, "정해 둔 시간이 지났어요.")
    decision = _decision_base(comment, mode)
    values: dict[str, Any] = {}
    if task.kind == "approval":
        decision["approved"] = mode in ("approve", "continue")
    else:
        defaults = dict(rules.get("default") or {})
        for f in task.fields or []:
            key = str(f.get("key") or "")
            if key:
                values[key] = defaults.get(key, "")
        values.update({k: v for k, v in defaults.items() if k not in values})
        decision["completed"] = True
        decision["response"] = values
    task.status = "done"
    task.response = {
        **values,
        **({"approved": decision["approved"]} if "approved" in decision else {}),
        "comment": comment,
        "timed_out": True,
        "timeout_mode": mode,
    }
    task.completed_at = now()
    task.completed_by = None
    run = db.get(Run, task.run_id) if task.run_id else None
    resumable = (
        run is not None
        and run.status == "waiting_approval"
        and bool(run.approval)
        and str((run.approval or {}).get("node_id") or "") in ("", task.node_id or "")
    )
    if run is not None and resumable:
        run.approval = {**(run.approval or {}), **decision}
    app = db.get(App, task.app_id)
    audit(
        db,
        workspace_id=app.workspace_id if app else task.workspace_id,
        user_id=None,
        action="task.timeout",
        target_type="task",
        target_id=task.id,
        meta={"mode": mode},
    )
    db.commit()
    return run if resumable else None


def _escalate(db: Session, task: HumanTask, current: datetime) -> bool:
    """기한이 지난 일을 올릴 곳(역할 이름 또는 사용자 id)에게 넘기고 기한을 같은 만큼 늘린다. 못 올리면 False."""
    rules = dict(task.rules or {})
    target = str(rules.get("escalate_to") or "").strip()
    if not target:
        return False
    hours = float(rules.get("hours") or 24)
    rules["escalated"] = True
    rules["reminded"] = False
    task.rules = rules
    task.due_at = current + timedelta(hours=hours)
    try:
        if target in ROLES:
            forward(
                db,
                task,
                by=None,
                to_role=target,
                comment="기한이 지나 위로 올렸어요.",
                via="timeout",
            )
        else:
            forward(
                db,
                task,
                by=None,
                to_user_id=target,
                comment="기한이 지나 위로 올렸어요.",
                via="timeout",
            )
    except AppError:
        db.rollback()
        return False
    return True


def apply_timeout(db: Session, task: HumanTask, current: datetime | None = None) -> Run | None:
    """기한이 지난 일에 정해 둔 처리를 한다. 이어서 실행할 Run(있으면)을 돌려준다."""
    current = current or now()
    rules = task.rules or {}
    mode = str(rules.get("on_timeout") or "none")
    if mode == "escalate":
        if not rules.get("escalated") and _escalate(db, task, current):
            return None
        mode = "reject"  # 올렸는데도 기한이 또 지났거나 올릴 곳이 없으면 마지막으로 반려(멈춤)
    if mode == "none":
        return None
    return _finish_by_timeout(db, task, mode)


def _send_reminder(db: Session, task: HumanTask) -> None:
    app = db.get(App, task.app_id)
    rules = dict(task.rules or {})
    rules["reminded"] = True  # 보내다 실패해도 같은 알림을 계속 보내지 않는다
    task.rules = rules
    if app is not None and rules.get("notify"):
        due = _aware(task.due_at)
        when = due.astimezone().strftime("%m월 %d일 %H시 %M분") if due else ""
        notify.send(
            db,
            task.workspace_id,
            dict(rules["notify"]),
            kind=task.kind,
            app_name=app.name,
            title=f"[기한 임박] {task.title}"[:300],
            detail=f"{when}까지 처리해야 해요.\n{task.detail}".strip(),
            token=task.token,
        )
    db.commit()


def sweep(db: Session, current: datetime | None = None) -> dict[str, list[str]]:
    """열린 일을 훑어 기한 지난 것은 정해 둔 대로 처리하고, 기한 직전인 것은 한 번 다시 알린다.

    돌려주는 값: {"resume": 이어서 실행할 run id들, "reminded": 알린 일 id들, "timed_out": 처리한 일 id들}.
    워커 beat가 5분마다 부르고(`genio.sweep_human_tasks`), 호출한 쪽이 resume을 큐에 넣는다.
    """
    cur = current or now()
    rows = list(
        db.scalars(
            select(HumanTask)
            .where(HumanTask.status == "open", HumanTask.due_at.is_not(None))
            .order_by(HumanTask.due_at)
            .limit(1000)
            .with_for_update(skip_locked=True)
        )
    )
    out: dict[str, list[str]] = {"resume": [], "reminded": [], "timed_out": []}
    for t in rows:
        due = _aware(t.due_at)
        if due is None:
            continue
        rules = t.rules or {}
        mode = str(rules.get("on_timeout") or "none")
        if due <= cur:
            if mode == "none":
                continue
            run = db.get(Run, t.run_id) if t.run_id else None
            if run is None or run.status != "waiting_approval":
                continue  # 실행이 이미 끝났거나 멈춘 일은 건드리지 않는다
            resumed = apply_timeout(db, t, cur)
            out["timed_out"].append(t.id)
            if resumed is not None:
                out["resume"].append(resumed.id)
            continue
        hours = rules.get("remind_before_hours")
        if hours and not rules.get("reminded") and cur >= due - timedelta(hours=float(hours)):
            _send_reminder(db, t)
            out["reminded"].append(t.id)
    return out
