"""v0.5 단계(기능 정의서 S7): 사람에게 묻기(ask_person), 할 일 맡기기(assign_task).

둘 다 승인 단계처럼 흐름을 멈추고 '작업함'과 링크로 사람이 처리하면 이어진다.
"""

from typing import Any

from nodes.builtin import NOTIFY_SCHEMA, NOTIFY_UI, notify_config
from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}
ROLES = ["owner", "admin", "builder", "operator", "member"]
FIELD_TYPES = ["text", "number", "paragraph", "choice"]


def _assignee(data: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    user = ctx.render(str(data.get("assignee_user_id") or "")).strip()
    role = str(data.get("assignee_role") or "").strip()
    if role and role not in ROLES:
        raise NodeError("담당 역할이 올바르지 않아요.")
    return {"assignee_user_id": user or None, "assignee_role": role or None}


def _due(data: dict[str, Any]) -> float | None:
    try:
        v = float(data.get("due_hours") or 0)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


# ---------------- 사람에게 묻기 ----------------
def _run_ask(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    question = ctx.render(str(data.get("question") or "")).strip()
    if not question:
        raise NodeError("사람에게 물어볼 내용을 적어 주세요.")
    fields = []
    for f in data.get("fields") or []:
        key = str(f.get("key") or "").strip()
        if not key:
            continue
        fields.append(
            {
                "key": key,
                "label": str(f.get("label") or key),
                "type": f.get("type") if f.get("type") in FIELD_TYPES else "text",
                "options": [str(o) for o in (f.get("options") or [])][:20],
                "required": bool(f.get("required", True)),
            }
        )
    if not fields:
        fields = [{"key": "answer", "label": "답", "type": "paragraph", "required": True}]
    return NodeResult(
        output={},
        wait_approval={
            "kind": "question",
            "message": question,
            "title": question[:300],
            "detail": ctx.render(str(data.get("detail") or "")),
            "fields": fields,
            "due_hours": _due(data),
            **_assignee(data, ctx),
            "notify": notify_config(data, ctx),
        },
    )


def _ask_outputs(data: dict[str, Any]) -> list[str]:
    keys = [str(f.get("key")) for f in data.get("fields") or [] if f.get("key")]
    return [*(keys or ["answer"]), "comment", "completed_by"]


ASK_PERSON = NodeSpec(
    type="ask_person",
    label="사람에게 묻기",
    category="흐름",
    description=(
        "흐름을 잠시 멈추고 담당자에게 필요한 정보를 물어요. 담당자가 작업함이나 링크에서 답하면 "
        "그 답을 가지고 다음 단계로 이어져요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "question": {"type": "string", "title": "물어볼 내용"},
            "detail": {"type": "string", "title": "참고 설명"},
            "fields": {
                "type": "array",
                "title": "받을 답",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "title": "이름(영문)"},
                        "label": {"type": "string", "title": "보여 줄 이름"},
                        "type": {
                            "type": "string",
                            "title": "종류",
                            "enum": FIELD_TYPES,
                            "enumNames": ["한 줄 글", "숫자", "여러 줄 글", "고르기"],
                            "default": "text",
                        },
                        "options": {
                            "type": "array",
                            "title": "고를 항목",
                            "items": {"type": "string"},
                        },
                        "required": {"type": "boolean", "title": "꼭 받기", "default": True},
                    },
                    "required": ["key"],
                },
            },
            "assignee_user_id": {"type": "string", "title": "담당자(사용자)"},
            "assignee_role": {
                "type": "string",
                "title": "담당 역할",
                "enum": ROLES,
                "enumNames": ["소유자", "관리자", "제작자", "운영자", "사용자"],
            },
            "due_hours": {"type": "number", "title": "기한(시간)", "minimum": 0},
            "notify": NOTIFY_SCHEMA,
        },
        "required": ["question"],
    },
    output_schema={"type": "object", "description": "받은 답(이름별) + comment, completed_by"},
    ui_schema={
        "question": {"ui:widget": "textarea"},
        "detail": {"ui:widget": "textarea"},
        "notify": NOTIFY_UI,
    },
    run=_run_ask,
    outputs=_ask_outputs,
)


# ---------------- 할 일 맡기기 ----------------
def _run_assign(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    title = ctx.render(str(data.get("title") or "")).strip()
    if not title:
        raise NodeError("맡길 일의 제목을 적어 주세요.")
    who = _assignee(data, ctx)
    if not who["assignee_user_id"] and not who["assignee_role"]:
        raise NodeError("담당자나 담당 역할을 골라 주세요.")
    return NodeResult(
        output={},
        wait_approval={
            "kind": "assignment",
            "message": title,
            "title": title[:300],
            "detail": ctx.render(str(data.get("detail") or "")),
            "fields": [],
            "due_hours": _due(data),
            **who,
            "notify": notify_config(data, ctx),
        },
    )


ASSIGN_TASK = NodeSpec(
    type="assign_task",
    label="할 일 맡기기",
    category="흐름",
    description=(
        "담당자에게 할 일을 맡기고, 담당자가 '완료'를 누를 때까지 흐름을 기다려요. "
        "완료하면서 남긴 한마디를 다음 단계에서 쓸 수 있어요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "title": {"type": "string", "title": "할 일"},
            "detail": {"type": "string", "title": "자세한 내용"},
            "assignee_user_id": {"type": "string", "title": "담당자(사용자)"},
            "assignee_role": {
                "type": "string",
                "title": "담당 역할",
                "enum": ROLES,
                "enumNames": ["소유자", "관리자", "제작자", "운영자", "사용자"],
            },
            "due_hours": {"type": "number", "title": "기한(시간)", "minimum": 0},
            "notify": NOTIFY_SCHEMA,
        },
        "required": ["title"],
    },
    output_schema={
        "type": "object",
        "properties": {"comment": {"type": "string"}, "completed_by": {"type": "string"}},
    },
    ui_schema={"detail": {"ui:widget": "textarea"}, "notify": NOTIFY_UI},
    run=_run_assign,
    outputs=lambda d: ["comment", "completed_by"],
)


V05_SPECS = [ASK_PERSON, ASSIGN_TASK]


def register_v05(reg: NodeRegistry) -> None:
    for spec in V05_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
