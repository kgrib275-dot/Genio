"""v0.6 외부 추적(ADR 0010): 끝난 실행을 Langfuse·LangSmith로 보낸다.

- 설정은 workspaces.settings["tracing"]에 둔다(마이그레이션 없음). 비밀값은 Fernet으로 암호화하고
  화면·응답에는 ****abcd로만 보여 준다. 일반 워크스페이스 조회 응답에서는 이 키를 뺀다.
- 실행이 끝나면(`_after_finish`) 켠 곳에만 보낸다. 워커가 있으면 큐로, 테스트(GENIO_RUN_INLINE)면 바로.
  전송 실패는 기록만 남기고 실행 결과에는 영향을 주지 않는다.
- 단계마다 span(AI 단계는 generation: 모델·토큰·비용·걸린 시간)을 만든다.
- 외부 호출은 safe_http(사설 IP 차단, GENIO_ALLOW_PRIVATE_NETWORK면 허용)를 거친다.
"""

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.core.crypto import decrypt_str, encrypt_str, mask, redact
from api.engine import safe_http
from api.engine.pricing import cost_of
from api.models import App, Run, RunStep, Workspace
from nodes import NodeError

log = logging.getLogger("genio.tracing")

SEND_TRACE = "genio.send_trace"
LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"
LANGSMITH_DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
# 한 값이 너무 길면 잘라 보낸다(외부 서비스 요청 크기 제한)
MAX_VALUE_CHARS = 4000
AI_TYPES = {"llm", "agent", "question_classifier", "parameter_extractor"}


# ---------------- 설정 ----------------
def _raw(ws: Workspace) -> dict[str, Any]:
    cfg = (ws.settings or {}).get("tracing")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _dec(value: Any) -> str:
    if not value:
        return ""
    try:
        return decrypt_str(str(value).encode())
    except ValueError:
        return ""


def _enc(value: str) -> str:
    return encrypt_str(value).decode()


def public_config(ws: Workspace) -> dict[str, Any]:
    """화면용 설정: 비밀값은 ****abcd로만."""
    cfg = _raw(ws)
    lf = dict(cfg.get("langfuse") or {})
    ls = dict(cfg.get("langsmith") or {})
    lf_secret = _dec(lf.get("secret_key_enc"))
    ls_key = _dec(ls.get("api_key_enc"))
    return {
        "langfuse": {
            "enabled": bool(lf.get("enabled")),
            "host": str(lf.get("host") or LANGFUSE_DEFAULT_HOST),
            "public_key": str(lf.get("public_key") or ""),
            "secret_key": mask(lf_secret) if lf_secret else "",
            "has_secret": bool(lf_secret),
        },
        "langsmith": {
            "enabled": bool(ls.get("enabled")),
            "endpoint": str(ls.get("endpoint") or LANGSMITH_DEFAULT_ENDPOINT),
            "project": str(ls.get("project") or "genio"),
            "api_key": mask(ls_key) if ls_key else "",
            "has_key": bool(ls_key),
        },
    }


def _clean_url(value: Any, default: str) -> str:
    url = str(value or "").strip().rstrip("/") or default
    if not url.startswith(("http://", "https://")):
        from api.core.errors import AppError

        raise AppError(
            422,
            "주소는 http:// 또는 https://로 시작해야 해요.",
            "예: https://cloud.langfuse.com 처럼 전체 주소를 넣어 주세요.",
        )
    return url[:300]


def save_config(ws: Workspace, body: dict[str, Any]) -> dict[str, Any]:
    """설정을 저장한다. 비밀값 칸이 비어 있으면 저장된 값을 그대로 둔다."""
    cfg = _raw(ws)
    lf = dict(cfg.get("langfuse") or {})
    ls = dict(cfg.get("langsmith") or {})
    lf_in = body.get("langfuse")
    if isinstance(lf_in, dict):
        lf["enabled"] = bool(lf_in.get("enabled"))
        lf["host"] = _clean_url(lf_in.get("host"), LANGFUSE_DEFAULT_HOST)
        lf["public_key"] = str(lf_in.get("public_key") or "").strip()[:200]
        secret = str(lf_in.get("secret_key") or "").strip()
        if secret and not secret.startswith("****"):
            lf["secret_key_enc"] = _enc(secret[:500])
        if lf_in.get("clear_secret"):
            lf.pop("secret_key_enc", None)
    ls_in = body.get("langsmith")
    if isinstance(ls_in, dict):
        ls["enabled"] = bool(ls_in.get("enabled"))
        ls["endpoint"] = _clean_url(ls_in.get("endpoint"), LANGSMITH_DEFAULT_ENDPOINT)
        ls["project"] = str(ls_in.get("project") or "genio").strip()[:100] or "genio"
        key = str(ls_in.get("api_key") or "").strip()
        if key and not key.startswith("****"):
            ls["api_key_enc"] = _enc(key[:500])
        if ls_in.get("clear_key"):
            ls.pop("api_key_enc", None)
    cfg["langfuse"] = lf
    cfg["langsmith"] = ls
    ws.settings = {**(ws.settings or {}), "tracing": cfg}
    return public_config(ws)


def _targets(ws: Workspace) -> dict[str, dict[str, str]]:
    """보낼 곳(켜져 있고 키가 있는 곳만). 비밀값이 풀린 상태이므로 밖으로 내보내지 않는다."""
    cfg = _raw(ws)
    out: dict[str, dict[str, str]] = {}
    lf = cfg.get("langfuse") or {}
    if lf.get("enabled"):
        secret = _dec(lf.get("secret_key_enc"))
        if secret and lf.get("public_key"):
            out["langfuse"] = {
                "host": str(lf.get("host") or LANGFUSE_DEFAULT_HOST),
                "public_key": str(lf["public_key"]),
                "secret_key": secret,
            }
    ls = cfg.get("langsmith") or {}
    if ls.get("enabled"):
        key = _dec(ls.get("api_key_enc"))
        if key:
            out["langsmith"] = {
                "endpoint": str(ls.get("endpoint") or LANGSMITH_DEFAULT_ENDPOINT),
                "project": str(ls.get("project") or "genio"),
                "api_key": key,
            }
    return out


def enabled(ws: Workspace | None) -> bool:
    if ws is None:
        return False
    cfg = _raw(ws)
    return any(bool((cfg.get(k) or {}).get("enabled")) for k in ("langfuse", "langsmith"))


# ---------------- 실행 → 추적 데이터 ----------------
def _iso(dt: datetime | None) -> str:
    d = dt or datetime.now(UTC)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _clip(value: Any) -> Any:
    """긴 값은 잘라 보낸다(JSON으로 바꿨을 때 MAX_VALUE_CHARS)."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= MAX_VALUE_CHARS:
        return value
    return text[:MAX_VALUE_CHARS] + "…(잘림)"


def _public_input(run: Run) -> dict[str, Any]:
    return {k: v for k, v in (run.input or {}).items() if not str(k).startswith("__")}


def _steps(db: Session, run_id: str) -> list[RunStep]:
    return list(db.scalars(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq)))


def _graph_types(run: Run, db: Session) -> dict[str, tuple[str, str]]:
    """단계 id → (타입, 화면 이름)."""
    from api.engine.executor import load_graph

    try:
        graph = load_graph(db, run)
    except NodeError:
        return {}
    return {n.id: (n.type, str(n.data.get("label") or n.type)) for n in graph.nodes}


def build_langfuse(db: Session, run: Run, app: App) -> list[dict[str, Any]]:
    """Langfuse 수집 API(/api/public/ingestion)용 이벤트 목록."""
    types = _graph_types(run, db)
    usage_by_node = dict((run.context or {}).get("usage") or {})
    now = _iso(None)
    trace = {
        "id": run.id,
        "timestamp": _iso(run.started_at or run.created_at),
        "name": app.name,
        "input": _clip(_public_input(run)),
        "output": _clip((run.output or {}).get("text") or run.error or ""),
        "metadata": {
            "app_id": app.id,
            "trigger": run.trigger,
            "status": run.status,
            "cost": float(run.cost or 0),
            "source": "genio",
        },
        "tags": ["genio", run.trigger or "run", run.status],
    }
    events: list[dict[str, Any]] = [
        {"id": f"{run.id}-trace", "type": "trace-create", "timestamp": now, "body": trace}
    ]
    for st in _steps(db, run.id):
        node_type, label = types.get(st.node_id, ("", st.node_id))
        body: dict[str, Any] = {
            "id": st.id,
            "traceId": run.id,
            "name": label,
            "startTime": _iso(st.started_at),
            "endTime": _iso(st.finished_at or st.started_at),
            "input": _clip(st.input),
            "output": _clip(st.output),
            "metadata": {"node_id": st.node_id, "type": node_type, "status": st.status},
            "level": "ERROR" if st.status == "failed" else "DEFAULT",
        }
        if st.status == "failed":
            body["statusMessage"] = _clip((st.logs or "").splitlines()[-1:] or "")
        usage = usage_by_node.get(st.node_id)
        if node_type in AI_TYPES or usage:
            u = usage or {}
            model = str(u.get("model") or (st.input or {}).get("model") or "")
            i, o = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
            body.update(
                {
                    "model": model or None,
                    "usage": {"input": i, "output": o, "total": i + o, "unit": "TOKENS"},
                    "costDetails": {"total": float(cost_of(model, i, o)) if model else 0.0},
                }
            )
            kind = "generation-create"
        else:
            kind = "span-create"
        events.append({"id": f"{st.id}-ev", "type": kind, "timestamp": now, "body": body})
    return events


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _dotted(ts: datetime | None, run_id: str) -> str:
    d = ts or datetime.now(UTC)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ") + run_id


def build_langsmith(db: Session, run: Run, app: App, project: str) -> list[dict[str, Any]]:
    """LangSmith 일괄 수집 API(/runs/batch)의 post 목록. 실행 = 루트(chain), 단계 = 자식."""
    types = _graph_types(run, db)
    usage_by_node = dict((run.context or {}).get("usage") or {})
    root_start = _aware(run.started_at or run.created_at) or datetime.now(UTC)
    root_order = _dotted(root_start, run.id)
    root: dict[str, Any] = {
        "id": run.id,
        "trace_id": run.id,
        "dotted_order": root_order,
        "name": app.name,
        "run_type": "chain",
        "inputs": _clip(_public_input(run)),
        "outputs": {"text": _clip((run.output or {}).get("text") or "")},
        "start_time": _iso(root_start),
        "end_time": _iso(run.finished_at or root_start),
        "session_name": project,
        "extra": {
            "metadata": {
                "app_id": app.id,
                "trigger": run.trigger,
                "status": run.status,
                "cost": float(run.cost or 0),
                "source": "genio",
            }
        },
        "tags": ["genio", run.trigger or "run"],
    }
    if run.status == "failed":
        root["error"] = run.error or "실패"
    out = [root]
    for st in _steps(db, run.id):
        node_type, label = types.get(st.node_id, ("", st.node_id))
        start = _aware(st.started_at) or root_start
        if start < root_start:
            start = root_start
        usage = usage_by_node.get(st.node_id)
        is_ai = node_type in AI_TYPES or bool(usage)
        child: dict[str, Any] = {
            "id": st.id,
            "trace_id": run.id,
            "parent_run_id": run.id,
            "dotted_order": f"{root_order}.{_dotted(start, st.id)}",
            "name": label,
            "run_type": "llm"
            if is_ai
            else ("tool" if node_type in ("http", "connector") else "chain"),
            "inputs": {"settings": _clip(st.input)},
            "outputs": {"result": _clip(st.output)},
            "start_time": _iso(start),
            "end_time": _iso(st.finished_at or start),
            "session_name": project,
            "extra": {"metadata": {"node_id": st.node_id, "type": node_type, "status": st.status}},
        }
        if is_ai:
            u = usage or {}
            model = str(u.get("model") or (st.input or {}).get("model") or "")
            i, o = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
            child["outputs"]["usage_metadata"] = {
                "input_tokens": i,
                "output_tokens": o,
                "total_tokens": i + o,
            }
            child["extra"]["metadata"].update(
                {"ls_model_name": model, "cost": float(cost_of(model, i, o)) if model else 0.0}
            )
        if st.status == "failed":
            child["error"] = ((st.logs or "").splitlines() or ["실패"])[-1]
        out.append(child)
    return out


# ---------------- 보내기 ----------------
def _post_langfuse(target: dict[str, str], events: list[dict[str, Any]]) -> str | None:
    """Langfuse로 보낸다. 실패하면 사용자에게 보여 줄 문장(비밀값 없음), 성공하면 None."""
    token = base64.b64encode(f"{target['public_key']}:{target['secret_key']}".encode()).decode()
    try:
        res = safe_http.request(
            "POST",
            f"{target['host'].rstrip('/')}/api/public/ingestion",
            headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
            body={"batch": events},
        )
    except NodeError as exc:
        return redact(exc.message, [target["secret_key"], target["public_key"]])
    status = int(res.get("status") or 0)
    if status in (401, 403):
        return "Langfuse가 키를 받아 주지 않았어요(인증 실패). 공개 키·비밀 키를 확인하세요."
    if status >= 400:
        return f"Langfuse가 요청을 받지 않았어요(응답 {status})."
    body = res.get("body")
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        return f"Langfuse가 일부 기록을 받지 않았어요({len(errors)}건)."
    return None


def _post_langsmith(target: dict[str, str], runs: list[dict[str, Any]]) -> str | None:
    try:
        res = safe_http.request(
            "POST",
            f"{target['endpoint'].rstrip('/')}/runs/batch",
            headers={"x-api-key": target["api_key"], "Content-Type": "application/json"},
            body={"post": runs},
        )
    except NodeError as exc:
        return redact(exc.message, [target["api_key"]])
    status = int(res.get("status") or 0)
    if status in (401, 403):
        return "LangSmith가 키를 받아 주지 않았어요(인증 실패). API 키를 확인하세요."
    if status >= 400:
        return f"LangSmith가 요청을 받지 않았어요(응답 {status})."
    return None


def send_run(db: Session, run_id: str) -> dict[str, str | None]:
    """실행 하나를 켠 곳에 보낸다. {곳: 실패 문장 | None}."""
    run = db.get(Run, run_id)
    if run is None:
        return {}
    app = db.get(App, run.app_id)
    ws = db.get(Workspace, app.workspace_id) if app else None
    if app is None or ws is None:
        return {}
    results: dict[str, str | None] = {}
    for name, target in _targets(ws).items():
        try:
            if name == "langfuse":
                results[name] = _post_langfuse(target, build_langfuse(db, run, app))
            else:
                results[name] = _post_langsmith(
                    target, build_langsmith(db, run, app, target["project"])
                )
        except Exception as exc:  # 추적은 실행에 영향을 주지 않는다
            log.warning("외부 추적 전송 오류(run=%s, %s): %s", run_id, name, type(exc).__name__)
            results[name] = "보내는 중 문제가 생겼어요."
        if results[name]:
            log.warning("외부 추적 전송 실패(run=%s, %s): %s", run_id, name, results[name])
    return results


def dispatch_trace(db: Session, run: Run) -> None:
    """끝난 실행을 보낼 차례에 올린다(켠 워크스페이스만)."""
    app = db.get(App, run.app_id)
    ws = db.get(Workspace, app.workspace_id) if app else None
    if not enabled(ws):
        return
    if get_settings().genio_run_inline:
        send_run(db, run.id)
        return
    from api.services.queue import _client

    _client().send_task(SEND_TRACE, args=[run.id])


# ---------------- 연결 시험 ----------------
def test_connection(db: Session, ws: Workspace, which: str) -> dict[str, Any]:
    """작은 시험 기록을 하나 보내 본다. 켜져 있지 않아도 키가 있으면 시험한다."""
    cfg = _raw(ws)
    now = datetime.now(UTC)
    test_id = f"genio-test-{int(now.timestamp())}"
    if which == "langfuse":
        lf = cfg.get("langfuse") or {}
        secret = _dec(lf.get("secret_key_enc"))
        if not secret or not lf.get("public_key"):
            return {"ok": False, "message": "공개 키와 비밀 키를 먼저 저장해 주세요."}
        target = {
            "host": str(lf.get("host") or LANGFUSE_DEFAULT_HOST),
            "public_key": str(lf["public_key"]),
            "secret_key": secret,
        }
        events = [
            {
                "id": f"{test_id}-ev",
                "type": "trace-create",
                "timestamp": _iso(now),
                "body": {"id": test_id, "name": "Genio 연결 시험", "tags": ["genio", "test"]},
            }
        ]
        err = _post_langfuse(target, events)
    elif which == "langsmith":
        ls = cfg.get("langsmith") or {}
        key = _dec(ls.get("api_key_enc"))
        if not key:
            return {"ok": False, "message": "API 키를 먼저 저장해 주세요."}
        import uuid

        rid = str(uuid.uuid4())
        target = {
            "endpoint": str(ls.get("endpoint") or LANGSMITH_DEFAULT_ENDPOINT),
            "project": str(ls.get("project") or "genio"),
            "api_key": key,
        }
        runs = [
            {
                "id": rid,
                "trace_id": rid,
                "dotted_order": _dotted(now, rid),
                "name": "Genio 연결 시험",
                "run_type": "chain",
                "inputs": {},
                "outputs": {"ok": True},
                "start_time": _iso(now),
                "end_time": _iso(now),
                "session_name": target["project"],
            }
        ]
        err = _post_langsmith(target, runs)
    else:
        return {"ok": False, "message": "알 수 없는 추적 서비스예요."}
    return (
        {
            "ok": True,
            "message": "시험 기록을 보냈어요. 상대 화면에서 'Genio 연결 시험'을 확인하세요.",
        }
        if err is None
        else {"ok": False, "message": err}
    )
