"""사람에게 맡기는 일(승인·질문·배정, 기능 정의서 S7).

흐름이 사람을 기다리는 단계(approval, ask_person, assign_task)에 닿으면 실행은 waiting_approval로
멈추고 HumanTask가 하나 생긴다. 작업함이나 링크(/t/{token})에서 처리하면 결정이 run.approval에
기록되고 실행이 그 단계 다음부터 이어진다.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from api.core.audit import audit
from api.core.errors import AppError
from api.core.security import random_token
from api.models import App, HumanTask, Run, User
from api.services import notify

KINDS = ("approval", "question", "assignment")


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
    if task.kind == "approval":
        roles = ((run.approval or {}) if run else {}).get("approver_roles") or []
        if roles:
            return role in roles
        return role in ("builder", "operator")
    if task.assignee_user_id:
        return task.assignee_user_id == user_id
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
    }
    if with_token:
        out["link"] = notify.task_link(task.token)
    return out
