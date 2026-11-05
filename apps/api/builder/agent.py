"""빌더 에이전트 루프(설계서 §6).

한 차례(사용자 메시지 1개) 동안:
1. 최근 20턴(텍스트만) + 현재 그래프 요약 + 앱 설명으로 컨텍스트를 만든다.
2. LLM이 툴을 부르면 실행하고 결과를 돌려준다. 그래프 변경은 graph_patch로 스트리밍한다.
3. ask_user·suggest_market_item을 부르면 그 차례를 끝내고 사용자를 기다린다.
4. 차례가 끝나면 어시스턴트 메시지(설명 + TurnRecord)를 builder_messages에 저장한다.

에이전트는 별도 스레드에서 돌고 이벤트를 큐로 넘긴다. SSE 응답은 큐를 읽어 보낸다.
"""

import json
import logging
import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.builder import metrics
from api.builder.graph_summary import summarize
from api.builder.tools import STOP_TOOLS, TOOL_DEFS, BuilderToolbox
from api.config import get_settings
from api.db import SessionLocal
from api.llm.base import ChatTurn, LlmError, Message
from api.llm.registry import ResolvedLlm, resolve_llm
from api.models import App, BuilderMessage, BuilderSession, MarketItem
from api.schemas.graph import Graph, empty_graph

log = logging.getLogger("genio.builder")
SYSTEM_PROMPT_PATH = Path(__file__).with_name("prompts") / "system.md"
HISTORY_TURNS = 20
MAX_STEPS = 24
Event = tuple[str, dict[str, Any]]
_DONE = object()


def system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def message_dict(m: BuilderMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "graph_patch": m.graph_patch,
        "created_at": m.created_at,
    }


def _history_text(m: BuilderMessage) -> str:
    """이전 차례는 텍스트로만 넘긴다(툴 단계·생각 단계를 다음 차례에 다시 보내지 않음)."""
    text = m.content or ""
    rec = m.graph_patch or {}
    extras = []
    calls = rec.get("tool_calls") or []
    if calls:
        extras.append(
            "[한 일] " + "; ".join(str(c.get("summary", "")) for c in calls if c.get("summary"))
        )
    if rec.get("ask_user"):
        q = rec["ask_user"]
        opts = ", ".join(q.get("options") or [])
        extras.append(f"[질문함] {q.get('question')}" + (f" (선택지: {opts})" if opts else ""))
    if rec.get("market_suggestion"):
        item = rec["market_suggestion"].get("item", {})
        extras.append(f"[설치 제안함] {item.get('name')}({item.get('key')})")
    if rec.get("test_result"):
        tr = rec["test_result"]
        extras.append(
            f"[테스트 실행] 상태={tr.get('status')} 결과={json.dumps(tr.get('output'), ensure_ascii=False)[:200]}"
        )
    if extras:
        text = (text + "\n" + "\n".join(extras)).strip()
    return text or "(빈 응답)"


def _resolve_builder_llm(db: Session, workspace_id: str) -> ResolvedLlm:
    s = get_settings()
    preferred = s.genio_builder_llm_provider
    try:
        llm = resolve_llm(db, workspace_id, preferred)
        if llm.provider.provider == "anthropic":
            # ADR 0001: 빌더 기본 모델(연결에 다른 기본 모델을 적었으면 그것을 따른다)
            llm.model = llm.provider.default_model or s.genio_builder_llm_model
        return llm
    except LlmError:
        return resolve_llm(db, workspace_id, "default")


def _context(db: Session, app: App, session_id: str, current_id: str) -> list[Message]:
    rows = list(
        db.scalars(
            select(BuilderMessage)
            .where(BuilderMessage.session_id == session_id, BuilderMessage.id != current_id)
            .order_by(BuilderMessage.created_at.desc())
            .limit(HISTORY_TURNS * 2)
        )
    )[::-1]
    messages: list[Message] = []
    for m in rows:
        role = "assistant" if m.role == "assistant" else "user"
        text = _history_text(m) if role == "assistant" else (m.content or "(빈 메시지)")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + text
        else:
            messages.append({"role": role, "content": text})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def _turn_system(app: App) -> str:
    graph = Graph.model_validate(app.draft_graph or empty_graph())
    return (
        system_prompt()
        + "\n\n# 지금 만드는 앱\n"
        + f"- 이름: {app.name}\n- 종류: {app.type}\n- 설명: {app.description or '(없음)'}\n"
        + "\n# 현재 흐름 요약(순번. id [타입] 이름)\n"
        + summarize(graph)
    )


def run_turn(
    session_id: str, user_id: str, content: str, event: dict[str, Any] | None
) -> Iterator[Event]:
    """SSE용 이벤트를 차례로 돌려준다. 에이전트는 별도 스레드에서 돈다."""
    q: queue.Queue[Any] = queue.Queue()

    def emit(name: str, data: dict[str, Any]) -> None:
        q.put((name, data))

    def worker() -> None:
        try:
            with SessionLocal() as db:
                _agent(db, session_id, user_id, content, event, emit)
        except Exception:
            log.exception("빌더 내부 오류(session=%s)", session_id)
            emit(
                "error",
                {"message": "빌더에서 문제가 생겼어요.", "hint": "잠시 후 다시 보내 주세요."},
            )
        finally:
            q.put(_DONE)

    threading.Thread(target=worker, daemon=True, name=f"builder-{session_id[:8]}").start()
    while True:
        item = q.get()
        if item is _DONE:
            return
        yield item


def _user_text(db: Session, content: str, event: dict[str, Any] | None) -> str:
    if event and event.get("type") == "installed":
        key = str(event.get("item_key", ""))
        item = db.scalar(select(MarketItem).where(MarketItem.key == key))
        name = item.name if item else key
        note = f"[알림] 사용자가 마켓에서 '{name}'({key})을(를) 설치했어요. 설치한 것을 써서 이어서 진행하세요."
        return f"{note}\n{content}".strip()
    return content


def _agent(
    db: Session,
    session_id: str,
    user_id: str,
    content: str,
    event: dict[str, Any] | None,
    emit: Any,
) -> None:
    sess = db.get(BuilderSession, session_id)
    if sess is None:
        emit("error", {"message": "빌더 대화를 찾을 수 없어요.", "hint": "화면을 새로고침하세요."})
        return
    app = db.get(App, sess.app_id)
    if app is None:
        emit("error", {"message": "앱을 찾을 수 없어요.", "hint": "앱 목록에서 다시 여세요."})
        return
    user_msg = BuilderMessage(
        session_id=session_id, role="user", content=_user_text(db, content, event)
    )
    db.add(user_msg)
    if not (event and event.get("type") == "installed" and not content.strip()):
        metrics.on_user_turn(sess)  # 설치 알림만 온 경우는 사용자 차례로 세지 않는다
    db.commit()
    emit("user_message", message_dict(user_msg))

    record: dict[str, Any] = {"ops": [], "tool_calls": []}
    text_parts: list[str] = []
    toolbox = BuilderToolbox(db, app, user_id)

    def save_assistant(text: str) -> None:
        msg = BuilderMessage(
            session_id=session_id, role="assistant", content=text, graph_patch=record
        )
        db.add(msg)
        db.commit()
        emit("done", message_dict(msg))

    try:
        llm = _resolve_builder_llm(db, app.workspace_id)
    except LlmError as exc:
        emit("error", {"message": exc.message, "hint": exc.hint})
        save_assistant(f"{exc.message} {exc.hint}")
        return

    messages = _context(db, app, session_id, user_msg.id)
    messages.append({"role": "user", "content": user_msg.content})
    if len(messages) >= 2 and messages[-2]["role"] == "user":
        last = messages.pop()
        messages[-1]["content"] += "\n\n" + last["content"]

    def on_text(delta: str) -> None:
        text_parts.append(delta)
        emit("text", {"delta": delta})

    stop = False
    changed_since_validate = False
    # 이 차례 안에서는 시스템 프롬프트를 바꾸지 않는다. Anthropic은 '생각 블록'을 만든 때와 시스템
    # 프롬프트가 다르면 그 블록을 거절(400)한다. 흐름이 바뀐 내용은 툴 결과에 붙여 AI에게 알린다.
    system_for_turn = _turn_system(app)
    for _ in range(MAX_STEPS):
        db.refresh(app)
        try:
            turn: ChatTurn = llm.adapter.chat(
                model=llm.model,
                system=system_for_turn,
                messages=messages,
                tools=TOOL_DEFS,
                on_text=on_text,
            )
        except LlmError as exc:
            emit("error", {"message": exc.message, "hint": exc.hint})
            text_parts.append(f"\n{exc.message} {exc.hint}")
            break
        if turn.text and not text_parts:
            # 스트리밍 콜백이 없던 어댑터
            pass
        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": turn.tool_calls,
                "native": turn.native,
            }
        )
        if not turn.tool_calls:
            break
        results: list[Message] = []
        round_changed = False
        for call in turn.tool_calls:
            emit("tool_call", {"id": call.id, "name": call.name, "input": call.input})
            if call.invalid_input is not None or turn.stop_reason == "max_tokens":
                outcome_ok, result, summary, ops, ev = (
                    False,
                    {"INVALID_JSON": call.invalid_input or ""},
                    "툴 입력을 읽지 못함",
                    [],
                    None,
                )
            else:
                outcome = toolbox.execute(call.name, call.input)
                outcome_ok, result, summary, ops, ev = (
                    outcome.ok,
                    outcome.result,
                    outcome.summary,
                    outcome.ops,
                    outcome.event,
                )
            record["tool_calls"].append(
                {
                    "id": call.id,
                    "name": call.name,
                    "input": call.input,
                    "ok": outcome_ok,
                    "summary": summary,
                }
            )
            emit(
                "tool_result",
                {"id": call.id, "name": call.name, "ok": outcome_ok, "summary": summary},
            )
            if ops:
                round_changed = True
                record["ops"].extend(ops)
                metrics.on_builder_ops(sess, len(ops))
                changed_since_validate = True
                db.refresh(app)
                emit(
                    "graph_patch",
                    {"ops": ops, "graph": app.draft_graph, "draft_rev": app.draft_rev},
                )
            if call.name == "validate" and outcome_ok and result.get("valid"):
                changed_since_validate = False
                metrics.on_validate_ok(sess)
            if ev is not None:
                name, payload = ev
                emit(name, payload)
                record[name] = payload
            if call.name in STOP_TOOLS and outcome_ok and ev is not None:
                stop = True
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                    "is_error": not outcome_ok,
                }
            )
        if round_changed and results:
            db.refresh(app)
            snapshot = summarize(Graph.model_validate(app.draft_graph or empty_graph()))
            results[-1]["content"] += "\n\n[지금 흐름 요약(방금 바뀐 내용 반영)]\n" + snapshot
        messages.extend(results)
        if stop:
            break
    else:
        note = "\n(한 번에 처리할 수 있는 작업량을 넘었어요. '계속'이라고 보내면 이어서 할게요.)"
        text_parts.append(note)
        emit("text", {"delta": note})

    text = "".join(text_parts).strip()
    claims_done = any(w in text for w in ("완료", "다 만들었", "완성"))
    if claims_done and (changed_since_validate or not toolbox.validated_ok) and record["ops"]:
        check = toolbox.execute("validate", {})
        if not check.result.get("valid"):
            errs = "; ".join(e["message"] for e in check.result.get("errors", [])[:3])
            note = f"\n\n잠깐, 아직 검증을 통과하지 못했어요. 고칠 부분: {errs}"
            emit("text", {"delta": note})
            text += note
    save_assistant(text)
