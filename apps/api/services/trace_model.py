"""v0.9 외부 추적: 실행 하나를 서비스에 상관없는 공통 모양(TraceRec)으로 모으고,
Langfuse·LangSmith·OpenTelemetry(OTLP, Phoenix·Arize 포함)·Opik·Weave가 받는 모양으로 바꾼다.

- 개인정보: 기본은 '내용 빼고 보내기'. 입력·결과·단계 설정·오류 원문은 워크스페이스가
  "입력·출력 내용 포함"을 켰을 때만 담고, 그때도 앱의 비밀 환경 값은 가리고 2KB로 자른다.
- 서비스 호출은 하지 않는다(보내기는 services/tracing.py).
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.crypto import decrypt_str
from api.engine.pricing import cost_of
from api.models import App, Run, RunStep
from nodes import NodeError

AI_TYPES = {"llm", "agent", "question_classifier", "parameter_extractor"}
TOOL_TYPES = {"http", "connector"}
# 내용(입력·결과)을 보낼 때 한 값의 최대 길이
MAX_TEXT = 2048
TRUNCATED = "…(잘림)"
GENERIC_ERROR = "단계가 실패했어요(내용은 보내지 않도록 설정돼 있어요)."


@dataclass
class StepRec:
    id: str
    node_id: str
    type: str
    label: str
    start: datetime
    end: datetime
    status: str
    kind: str  # llm | tool | chain
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    error: str = ""
    input: Any = None
    output: Any = None


@dataclass
class TraceRec:
    run_id: str
    app_id: str
    app_name: str
    trigger: str
    status: str
    start: datetime
    end: datetime
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    include_content: bool = False
    input: Any = None
    output: Any = None
    steps: list[StepRec] = field(default_factory=list)


# ---------------- 도우미 ----------------
def aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def iso(dt: datetime | None) -> str:
    d = aware(dt) or datetime.now(UTC)
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


def unix_nano(dt: datetime | None) -> str:
    """OTLP/JSON의 시각: 1970년부터의 나노초(64비트 정수라서 문자열)."""
    d = (aware(dt) or datetime.now(UTC)).astimezone(UTC)
    return str(int(d.timestamp()) * 1_000_000_000 + d.microsecond * 1000)


def hex_trace_id(run_id: str) -> str:
    """OTLP trace id: 소문자 16진수 32자(전부 0이면 안 된다)."""
    try:
        value = uuid.UUID(str(run_id)).hex
    except ValueError:
        value = hashlib.sha256(str(run_id).encode()).hexdigest()[:32]
    return value if int(value, 16) else "1".rjust(32, "0")


def hex_span_id(key: str) -> str:
    """OTLP span id: 소문자 16진수 16자(같은 키는 늘 같은 값)."""
    value = hashlib.sha256(key.encode()).hexdigest()[:16]
    return value if int(value, 16) else "1".rjust(16, "0")


def uuid7(ts: datetime, seed: str) -> str:
    """시각 순서가 있는 UUID v7(Opik이 요구). 같은 seed는 늘 같은 값."""
    ms = int(ts.timestamp() * 1000) & ((1 << 48) - 1)
    rnd = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:10], "big")  # 80비트
    rand_a = (rnd >> 68) & 0xFFF
    rand_b = rnd & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def stable_uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"genio:{seed}"))


def secret_values(app: App) -> list[str]:
    """앱의 비밀 환경 값(평문). 내용을 보낼 때 이 값이 들어 있으면 가린다."""
    out: list[str] = []
    for v in app.env_vars or []:
        if v.get("secret") and v.get("value_enc"):
            try:
                text = decrypt_str(str(v["value_enc"]).encode("ascii"))
            except ValueError:
                continue
            if len(text) >= 4:
                out.append(text)
    return out


def clip(value: Any, secrets: list[str]) -> Any:
    """내용 값: 비밀을 가리고 MAX_TEXT로 자른다(자르거나 가렸으면 글로 돌려준다)."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    hidden = text
    for s in secrets:
        hidden = hidden.replace(s, "****")
    if len(hidden) <= MAX_TEXT:
        return value if hidden == text else hidden
    return hidden[:MAX_TEXT] + TRUNCATED


def _graph_types(run: Run, db: Session) -> dict[str, tuple[str, str]]:
    from api.engine.executor import load_graph

    try:
        graph = load_graph(db, run)
    except NodeError:
        return {}
    return {n.id: (n.type, str(n.data.get("label") or n.type)) for n in graph.nodes}


def _public_input(run: Run) -> dict[str, Any]:
    return {k: v for k, v in (run.input or {}).items() if not str(k).startswith("__")}


def collect(db: Session, run: Run, app: App, include_content: bool) -> TraceRec:
    """실행 하나를 공통 모양으로. include_content가 꺼져 있으면 입력·결과·오류 원문은 담지 않는다."""
    types = _graph_types(run, db)
    usage_by_node = dict((run.context or {}).get("usage") or {})
    secrets = secret_values(app) if include_content else []
    start = aware(run.started_at or run.created_at) or datetime.now(UTC)
    end = aware(run.finished_at) or start
    if end < start:
        end = start
    rec = TraceRec(
        run_id=run.id,
        app_id=app.id,
        app_name=app.name,
        trigger=run.trigger or "run",
        status=run.status,
        start=start,
        end=end,
        cost=float(run.cost or 0),
        include_content=include_content,
    )
    if include_content:
        rec.input = clip(_public_input(run), secrets)
        rec.output = clip((run.output or {}).get("text") or "", secrets)
    if run.status == "failed":
        rec.error = (
            str(clip(run.error or "실패", secrets)) if include_content else "실행이 실패했어요."
        )
    rows = list(db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq)))
    for st in rows:
        node_type, label = types.get(st.node_id, ("", st.node_id))
        usage = usage_by_node.get(st.node_id)
        is_ai = node_type in AI_TYPES or bool(usage)
        u = usage or {}
        model = str(u.get("model") or (st.input or {}).get("model") or "") if is_ai else ""
        i, o = (
            (int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)) if is_ai else (0, 0)
        )
        s_start = max(aware(st.started_at) or start, start)
        s_end = max(aware(st.finished_at) or s_start, s_start)
        step = StepRec(
            id=st.id,
            node_id=st.node_id,
            type=node_type,
            label=label,
            start=s_start,
            end=s_end,
            status=st.status,
            kind="llm" if is_ai else ("tool" if node_type in TOOL_TYPES else "chain"),
            model=model,
            input_tokens=i,
            output_tokens=o,
            cost=float(cost_of(model, i, o)) if model else 0.0,
        )
        if st.status == "failed":
            last = ((st.logs or "").splitlines() or ["실패"])[-1]
            step.error = str(clip(last, secrets)) if include_content else GENERIC_ERROR
        if include_content:
            step.input = clip(st.input, secrets)
            step.output = clip(st.output, secrets)
        rec.input_tokens += i
        rec.output_tokens += o
        rec.steps.append(step)
    return rec


def test_record(now: datetime | None = None) -> TraceRec:
    """연결 시험용 작은 기록(내용 없음)."""
    t = aware(now) or datetime.now(UTC)
    rid = str(uuid.uuid4())
    rec = TraceRec(
        run_id=rid,
        app_id="genio-test",
        app_name="Genio 연결 시험",
        trigger="test",
        status="succeeded",
        start=t,
        end=t,
    )
    rec.steps.append(
        StepRec(
            id=str(uuid.uuid4()),
            node_id="test",
            type="template",
            label="시험 단계",
            start=t,
            end=t,
            status="succeeded",
            kind="chain",
        )
    )
    return rec


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ---------------- Langfuse ----------------
def build_langfuse(rec: TraceRec) -> list[dict[str, Any]]:
    """Langfuse 수집 API(/api/public/ingestion)용 이벤트 목록."""
    now = iso(None)
    trace = _drop_none(
        {
            "id": rec.run_id,
            "timestamp": iso(rec.start),
            "name": rec.app_name,
            "input": rec.input,
            "output": rec.output,
            "metadata": {
                "app_id": rec.app_id,
                "trigger": rec.trigger,
                "status": rec.status,
                "cost": rec.cost,
                "source": "genio",
            },
            "tags": ["genio", rec.trigger, rec.status],
        }
    )
    events: list[dict[str, Any]] = [
        {"id": f"{rec.run_id}-trace", "type": "trace-create", "timestamp": now, "body": trace}
    ]
    for st in rec.steps:
        body: dict[str, Any] = _drop_none(
            {
                "id": st.id,
                "traceId": rec.run_id,
                "name": st.label,
                "startTime": iso(st.start),
                "endTime": iso(st.end),
                "input": st.input,
                "output": st.output,
                "metadata": {"node_id": st.node_id, "type": st.type, "status": st.status},
                "level": "ERROR" if st.status == "failed" else "DEFAULT",
                "statusMessage": st.error or None,
            }
        )
        if st.kind == "llm":
            body.update(
                {
                    "model": st.model or None,
                    "usage": {
                        "input": st.input_tokens,
                        "output": st.output_tokens,
                        "total": st.input_tokens + st.output_tokens,
                        "unit": "TOKENS",
                    },
                    "costDetails": {"total": st.cost},
                }
            )
            kind = "generation-create"
        else:
            kind = "span-create"
        events.append({"id": f"{st.id}-ev", "type": kind, "timestamp": now, "body": body})
    return events


# ---------------- LangSmith ----------------
def _dotted(ts: datetime, key: str) -> str:
    return (aware(ts) or ts).astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ") + key


def build_langsmith(rec: TraceRec, project: str) -> list[dict[str, Any]]:
    """LangSmith 일괄 수집 API(/runs/batch)의 post 목록. 실행 = 루트(chain), 단계 = 자식."""
    root_order = _dotted(rec.start, rec.run_id)
    root: dict[str, Any] = _drop_none(
        {
            "id": rec.run_id,
            "trace_id": rec.run_id,
            "dotted_order": root_order,
            "name": rec.app_name,
            "run_type": "chain",
            "inputs": rec.input if rec.input is not None else {},
            "outputs": {"text": rec.output} if rec.output is not None else {},
            "start_time": iso(rec.start),
            "end_time": iso(rec.end),
            "session_name": project,
            "extra": {
                "metadata": {
                    "app_id": rec.app_id,
                    "trigger": rec.trigger,
                    "status": rec.status,
                    "cost": rec.cost,
                    "source": "genio",
                }
            },
            "tags": ["genio", rec.trigger],
            "error": rec.error or None,
        }
    )
    out = [root]
    for st in rec.steps:
        child: dict[str, Any] = {
            "id": st.id,
            "trace_id": rec.run_id,
            "parent_run_id": rec.run_id,
            "dotted_order": f"{root_order}.{_dotted(st.start, st.id)}",
            "name": st.label,
            "run_type": st.kind,
            "inputs": {"settings": st.input} if st.input is not None else {},
            "outputs": {"result": st.output} if st.output is not None else {},
            "start_time": iso(st.start),
            "end_time": iso(st.end),
            "session_name": project,
            "extra": {"metadata": {"node_id": st.node_id, "type": st.type, "status": st.status}},
        }
        if st.kind == "llm":
            child["outputs"]["usage_metadata"] = {
                "input_tokens": st.input_tokens,
                "output_tokens": st.output_tokens,
                "total_tokens": st.input_tokens + st.output_tokens,
            }
            child["extra"]["metadata"].update({"ls_model_name": st.model, "cost": st.cost})
        if st.error:
            child["error"] = st.error
        out.append(child)
    return out


# ---------------- OpenTelemetry(OTLP/JSON), Phoenix, Arize ----------------
def _kv(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        v: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}  # int64는 문자열(OTLP/JSON)
    elif isinstance(value, float):
        v = {"doubleValue": value}
    else:
        v = {"stringValue": str(value)}
    return {"key": key, "value": v}


def _attrs(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [_kv(k, v) for k, v in d.items() if v is not None and v != ""]


def _system_of(model: str) -> str:
    m = model.lower()
    if "claude" in m:
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4")) or "gpt" in m:
        return "openai"
    if "gemini" in m:
        return "google"
    return "unknown"


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def build_otlp(
    rec: TraceRec,
    *,
    service_name: str = "genio",
    resource: dict[str, Any] | None = None,
    openinference: bool = False,
) -> dict[str, Any]:
    """OTLP/HTTP JSON(`POST /v1/traces`) 본문. 실행 = 루트 span, 단계 = 자식 span.

    AI 단계에는 GenAI 표준 속성(gen_ai.*)을 붙이고, openinference=True면 Phoenix·Arize가 읽는
    OpenInference 속성(span kind, llm.*, input/output.value)도 함께 붙인다.
    """
    trace_id = hex_trace_id(rec.run_id)
    root_id = hex_span_id(f"run:{rec.run_id}")
    ok = {"code": 1}
    fail = {"code": 2, "message": rec.error or "실패"}
    root_attrs: dict[str, Any] = {
        "genio.app": rec.app_name,
        "genio.app_id": rec.app_id,
        "genio.run_id": rec.run_id,
        "genio.trigger": rec.trigger,
        "genio.status": rec.status,
        "genio.cost": rec.cost,
        "genio.tokens.input": rec.input_tokens,
        "genio.tokens.output": rec.output_tokens,
    }
    if openinference:
        root_attrs["openinference.span.kind"] = "CHAIN"
    if rec.include_content and rec.input is not None:
        root_attrs["input.value"] = _text(rec.input)
    if rec.include_content and rec.output is not None:
        root_attrs["output.value"] = _text(rec.output)
    spans: list[dict[str, Any]] = [
        {
            "traceId": trace_id,
            "spanId": root_id,
            "name": rec.app_name,
            "kind": 1,
            "startTimeUnixNano": unix_nano(rec.start),
            "endTimeUnixNano": unix_nano(rec.end),
            "attributes": _attrs(root_attrs),
            "status": fail if rec.status == "failed" else ok,
        }
    ]
    for st in rec.steps:
        a: dict[str, Any] = {
            "genio.node_id": st.node_id,
            "genio.node_type": st.type,
            "genio.step_status": st.status,
        }
        if st.kind == "llm":
            a.update(
                {
                    "gen_ai.system": _system_of(st.model),
                    "gen_ai.request.model": st.model,
                    "gen_ai.usage.input_tokens": st.input_tokens,
                    "gen_ai.usage.output_tokens": st.output_tokens,
                    "genio.cost": st.cost,
                }
            )
        if openinference:
            a["openinference.span.kind"] = {"llm": "LLM", "tool": "TOOL"}.get(st.kind, "CHAIN")
            if st.kind == "llm":
                a.update(
                    {
                        "llm.model_name": st.model,
                        "llm.token_count.prompt": st.input_tokens,
                        "llm.token_count.completion": st.output_tokens,
                        "llm.token_count.total": st.input_tokens + st.output_tokens,
                    }
                )
        if rec.include_content and st.input is not None:
            a["input.value"] = _text(st.input)
        if rec.include_content and st.output is not None:
            a["output.value"] = _text(st.output)
        spans.append(
            {
                "traceId": trace_id,
                "spanId": hex_span_id(f"step:{st.id}"),
                "parentSpanId": root_id,
                "name": st.label,
                "kind": 1,
                "startTimeUnixNano": unix_nano(st.start),
                "endTimeUnixNano": unix_nano(st.end),
                "attributes": _attrs(a),
                "status": {"code": 2, "message": st.error or "실패"}
                if st.status == "failed"
                else ok,
            }
        )
    res = {"service.name": service_name, **(resource or {})}
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attrs(res)},
                "scopeSpans": [{"scope": {"name": "genio", "version": "0.9"}, "spans": spans}],
            }
        ]
    }


# ---------------- Opik ----------------
def build_opik(rec: TraceRec, project: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Opik REST: (traces, spans). id는 UUID v7."""
    trace_uuid = uuid7(rec.start, f"trace:{rec.run_id}")
    trace = _drop_none(
        {
            "id": trace_uuid,
            "project_name": project,
            "name": rec.app_name,
            "start_time": iso(rec.start),
            "end_time": iso(rec.end),
            "input": {"text": rec.input} if rec.input is not None else {},
            "output": {"text": rec.output} if rec.output is not None else {},
            "metadata": {
                "source": "genio",
                "app_id": rec.app_id,
                "trigger": rec.trigger,
                "status": rec.status,
                "cost": rec.cost,
                "run_id": rec.run_id,
                "error": rec.error or None,
            },
            "tags": ["genio", rec.trigger, rec.status],
        }
    )
    spans: list[dict[str, Any]] = []
    for st in rec.steps:
        span: dict[str, Any] = _drop_none(
            {
                "id": uuid7(st.start, f"span:{st.id}"),
                "trace_id": trace_uuid,
                "project_name": project,
                "name": st.label,
                "type": {"llm": "llm", "tool": "tool"}.get(st.kind, "general"),
                "start_time": iso(st.start),
                "end_time": iso(st.end),
                "input": {"settings": st.input} if st.input is not None else {},
                "output": {"result": st.output} if st.output is not None else {},
                "metadata": {
                    "node_id": st.node_id,
                    "node_type": st.type,
                    "status": st.status,
                    "error": st.error or None,
                },
            }
        )
        if st.kind == "llm":
            span.update(
                {
                    "model": st.model or None,
                    "provider": _system_of(st.model),
                    "usage": {
                        "prompt_tokens": st.input_tokens,
                        "completion_tokens": st.output_tokens,
                        "total_tokens": st.input_tokens + st.output_tokens,
                    },
                    "total_estimated_cost": st.cost,
                }
            )
        spans.append(span)
    return [trace], spans


# ---------------- Weave ----------------
def build_weave(rec: TraceRec, project_id: str) -> list[dict[str, Any]]:
    """Weave trace 서버 `/call/upsert_batch`의 batch 항목(시작·끝 쌍)."""
    trace_id = stable_uuid(f"trace:{rec.run_id}")
    root_id = stable_uuid(f"run:{rec.run_id}")
    batch: list[dict[str, Any]] = []

    def pair(
        call_id: str,
        parent: str | None,
        name: str,
        start: datetime,
        end: datetime,
        inputs: dict[str, Any],
        output: Any,
        attributes: dict[str, Any],
        summary: dict[str, Any],
        error: str,
    ) -> None:
        batch.append(
            {
                "mode": "start",
                "req": {
                    "start": {
                        "project_id": project_id,
                        "id": call_id,
                        "op_name": name,
                        "display_name": name,
                        "trace_id": trace_id,
                        "parent_id": parent,
                        "started_at": iso(start),
                        "attributes": attributes,
                        "inputs": inputs,
                    }
                },
            }
        )
        batch.append(
            {
                "mode": "end",
                "req": {
                    "end": {
                        "project_id": project_id,
                        "id": call_id,
                        "ended_at": iso(end),
                        "exception": error or None,
                        "output": output,
                        "summary": summary,
                    }
                },
            }
        )

    pair(
        root_id,
        None,
        rec.app_name,
        rec.start,
        rec.end,
        {"input": rec.input} if rec.input is not None else {},
        {"text": rec.output} if rec.output is not None else {"status": rec.status},
        {"source": "genio", "app_id": rec.app_id, "trigger": rec.trigger, "cost": rec.cost},
        {},
        rec.error,
    )
    for st in rec.steps:
        summary: dict[str, Any] = {}
        if st.kind == "llm" and st.model:
            summary["usage"] = {
                st.model: {
                    "requests": 1,
                    "prompt_tokens": st.input_tokens,
                    "completion_tokens": st.output_tokens,
                    "total_tokens": st.input_tokens + st.output_tokens,
                }
            }
        pair(
            stable_uuid(f"step:{st.id}"),
            root_id,
            st.label,
            st.start,
            st.end,
            {"settings": st.input} if st.input is not None else {},
            {"result": st.output} if st.output is not None else {"status": st.status},
            {"node_id": st.node_id, "node_type": st.type, "status": st.status},
            summary,
            st.error,
        )
    return batch
