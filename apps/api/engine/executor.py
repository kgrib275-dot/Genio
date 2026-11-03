"""워크플로우 실행 엔진(설계서 §5).

- 입력 노드에서 시작해 선택된 분기만 따라 순차 실행한다(병렬 분기 미지원).
- 노드마다 run_steps에 기록하고 Redis로 알린다.
- approval 노드에서 멈추고(waiting_approval), 승인되면 다음 노드부터 다시 이어 간다.
- http·connector는 지수 백오프로 2회 재시도, 노드 60초·실행 10분 제한.
- LLM 토큰 × 단가표로 비용을 계산한다.
"""

import concurrent.futures
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.connectors.runtime import run_connector
from api.db import SessionLocal
from api.engine import events, safe_http
from api.engine.code_runner import get_code_runner
from api.engine.pricing import cost_of
from api.engine.templating import TemplateRenderError, evaluate, render, render_value
from api.llm.base import LlmError
from api.llm.registry import resolve_llm
from api.market.service import ensure_market_nodes
from api.models import App, Run, RunStep, StoredFile, WorkflowVersion
from api.schemas.graph import Graph
from api.services import knowledge
from api.services.app_config import decrypt_env_vars
from nodes import LlmResult, NodeContext, NodeError, NodeResult, registry

log = logging.getLogger("genio.engine")
TERMINAL = {"succeeded", "failed"}


def now() -> datetime:
    return datetime.now(UTC)


class RunServices:
    """노드가 쓰는 외부 자원. 노드 쪽에는 비밀값이 넘어가지 않는다."""

    def __init__(self, db: Session, workspace_id: str) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.usage: list[tuple[str, int, int]] = []
        self.depth = 0

    def llm_complete(
        self,
        *,
        provider: str,
        model: str | None,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
    ) -> LlmResult:
        try:
            llm = resolve_llm(self.db, self.workspace_id, provider, model)
            result = llm.adapter.complete(
                model=llm.model,
                system=system,
                prompt=prompt,
                temperature=temperature,
                json_schema=json_schema,
            )
        except LlmError as exc:
            raise NodeError(f"{exc.message} {exc.hint}", retryable=exc.retryable) from None
        result.model = result.model or llm.model
        self.usage.append((result.model, result.input_tokens, result.output_tokens))
        return result

    def http_request(
        self, *, method: str, url: str, headers: dict[str, str], body: Any
    ) -> dict[str, Any]:
        return safe_http.request(method, url, headers=headers, body=body)

    def kb_search(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int,
        method: str | None = None,
        score_threshold: float | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return knowledge.search(
            self.db,
            self.workspace_id,
            kb_id,
            query,
            top_k,
            method=method,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
        )

    def run_connector(
        self, *, connector: str, credential_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return run_connector(
            self.db,
            self.workspace_id,
            connector=connector,
            credential_id=credential_id,
            action=action,
            params=params,
        )

    def run_code(self, *, code: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return get_code_runner().run(code, inputs)

    # ---- v0.2 ----
    def read_file(self, *, file_id: str) -> tuple[str, str, bytes]:
        f = self.db.get(StoredFile, file_id)
        if f is None or f.workspace_id != self.workspace_id:
            raise NodeError("파일을 찾을 수 없어요. 다시 올려 주세요.")
        return f.filename, f.mime, f.content

    def extract_text(self, *, filename: str, mime: str, content: bytes) -> str:
        try:
            return knowledge.extract_text(content, filename, mime)
        except ValueError as exc:
            raise NodeError(str(exc)) from None

    def run_agent(
        self,
        *,
        provider: str,
        model: str | None,
        instruction: str,
        query: str,
        tools: list[dict[str, Any]],
        max_iterations: int,
    ) -> dict[str, Any]:
        from api.engine.agent import run_agent

        return run_agent(
            self,
            provider=provider,
            model=model,
            instruction=instruction,
            query=query,
            tools=tools,
            max_iterations=max_iterations,
        )

    def connector_manifest(self, key: str) -> dict[str, Any] | None:
        from api.market.service import connector_manifest

        return connector_manifest(self.db, self.workspace_id, key)


def _next(graph: Graph, node_id: str, handle: str | None) -> str | None:
    edges = [e for e in graph.edges if e.source == node_id]
    if handle is not None:
        edge = next((e for e in edges if e.source_handle == handle), None)
    else:
        edge = next((e for e in edges if not e.source_handle), None)
    return edge.target if edge else None


def _share_logs(child: NodeContext, parent: NodeContext) -> NodeContext:
    """하위 동작의 로그를 부모 단계 로그에 함께 남긴다."""
    child.logs = parent.logs
    return child


def _publish(run: Run, step: RunStep | None = None) -> None:
    events.publish(
        run.id, {"run_id": run.id, "status": run.status, "step_id": step.id if step else None}
    )


def _label(graph: Graph, node_id: str) -> str:
    node = graph.node(node_id)
    if node is None:
        return node_id
    return str(node.data.get("label") or node.type)


def load_graph(db: Session, run: Run) -> Graph:
    if run.graph_snapshot:
        return Graph.model_validate(run.graph_snapshot)
    if run.version_id:
        version = db.get(WorkflowVersion, run.version_id)
        if version is not None:
            return Graph.model_validate(version.graph)
    raise NodeError("실행할 흐름을 찾지 못했어요.")


def _run_with_limits(
    fn: Any,
    data: dict[str, Any],
    ctx: NodeContext,
    retries: int,
    interval: float | None = None,
    retry_all: bool = False,
) -> NodeResult:
    timeout = get_settings().genio_node_timeout_seconds
    attempt = 0
    while True:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(fn, data, ctx)
        try:
            result: NodeResult = future.result(timeout=timeout)
            pool.shutdown(wait=False)
            return result
        except concurrent.futures.TimeoutError:
            pool.shutdown(wait=False, cancel_futures=True)
            raise NodeError(f"{timeout:.0f}초 안에 끝나지 않아 멈췄어요.") from None
        except NodeError as exc:
            pool.shutdown(wait=False)
            if attempt < retries and (exc.retryable or retry_all):
                attempt += 1
                delay = interval if interval is not None else 0.5 * (2 ** (attempt - 1))
                ctx.log(
                    f"실패해서 {delay:.1f}초 뒤 다시 시도해요({attempt}/{retries}): {exc.message}"
                )
                time.sleep(delay)
                continue
            raise


def execute_run(run_id: str, *, db: Session | None = None) -> None:
    own = db is None
    session = db or SessionLocal()
    try:
        _execute(session, run_id)
    except Exception:
        log.exception("실행 엔진 내부 오류(run=%s)", run_id)
        session.rollback()
        run = session.get(Run, run_id)
        if run is not None and run.status not in TERMINAL:
            run.status = "failed"
            run.error = "실행 중 예상하지 못한 문제가 생겼어요. 잠시 후 다시 실행해 보세요."
            run.finished_at = now()
            session.commit()
            _publish(run)
    finally:
        if own:
            session.close()


def _finish(
    db: Session, run: Run, services: RunServices, status: str, error: str | None = None
) -> None:
    usage = dict(run.token_usage or {})
    inp = int(usage.get("input_tokens", 0))
    out = int(usage.get("output_tokens", 0))
    cost = Decimal(str(run.cost or 0))
    for model, i, o in services.usage:
        inp += i
        out += o
        cost += cost_of(model, i, o)
    services.usage.clear()
    run.token_usage = {"input_tokens": inp, "output_tokens": out}
    run.cost = cost
    run.status = status
    if error is not None:
        run.error = error
    if status in TERMINAL:
        run.finished_at = now()
    db.commit()
    _publish(run)


def _execute(db: Session, run_id: str) -> None:
    run = db.get(Run, run_id)
    if run is None or run.status in TERMINAL:
        return
    app = db.get(App, run.app_id)
    if app is None:
        return
    ensure_market_nodes(db)
    services = RunServices(db, app.workspace_id)
    try:
        graph = load_graph(db, run)
    except NodeError as exc:
        _finish(db, run, services, "failed", exc.message)
        return

    outputs: dict[str, dict[str, Any]] = dict((run.context or {}).get("outputs", {}))
    run_input: dict[str, Any] = dict(run.input or {})
    env_vars = decrypt_env_vars(app.env_vars or [])
    conv_vars: dict[str, Any] = dict(
        (run.context or {}).get("conv") or run_input.pop("__conv", None) or {}
    )
    services.depth = int(run_input.pop("__depth", 0) or 0)
    current: str | None
    if run.status == "waiting_approval":
        # approve API가 결정을 기록한 뒤 이 함수를 다시 부른다
        approval = run.approval or {}
        if "approved" not in approval:
            return
        node_id = str(approval.get("node_id"))
        step = db.scalar(
            select(RunStep)
            .where(RunStep.run_id == run.id, RunStep.node_id == node_id)
            .order_by(RunStep.seq.desc())
        )
        result_out = {
            "approved": bool(approval["approved"]),
            "comment": approval.get("comment") or "",
            "approver": approval.get("decided_by_name") or "",
        }
        if step is not None:
            step.output = result_out
            step.finished_at = now()
            step.status = "succeeded" if approval["approved"] else "failed"
        if not approval["approved"]:
            _finish(db, run, services, "failed", "승인이 거절되어 흐름을 멈췄어요.")
            return
        outputs[node_id] = result_out
        run.status = "running"
        db.commit()
        _publish(run, step)
        current = _next(graph, node_id, None)
    else:
        start = next((n for n in graph.nodes if n.type == "input"), None)
        if start is None:
            _finish(db, run, services, "failed", "입력 노드가 없어 실행할 수 없어요.")
            return
        run.status = "running"
        run.started_at = now()
        db.commit()
        _publish(run)
        current = start.id

    # 사람 승인을 기다린 시간은 빼고, 이번 실행 구간이 시작된 때부터 잰다
    deadline = time.time() + get_settings().genio_run_timeout_seconds
    visited = 0
    step_seq = db.scalar(select(func.max(RunStep.seq)).where(RunStep.run_id == run.id)) or 0
    last_output_text = str((run.output or {}).get("text", ""))
    output_values: dict[str, Any] = dict((run.output or {}).get("outputs", {}))
    while current is not None:
        visited += 1
        if visited > len(graph.nodes) + 1:
            _finish(db, run, services, "failed", "흐름이 끝나지 않아 멈췄어요. 연결을 확인하세요.")
            return
        if time.time() > deadline:
            _finish(db, run, services, "failed", "실행 시간이 10분을 넘어 멈췄어요.")
            return
        node = graph.node(current)
        if node is None:
            _finish(db, run, services, "failed", f"'{current}' 노드를 찾지 못했어요.")
            return
        spec = registry.get(node.type)
        step_seq += 1
        step = RunStep(
            run_id=run.id,
            node_id=node.id,
            status="running",
            input=node.data,
            started_at=now(),
            seq=step_seq,
        )
        db.add(step)
        db.commit()
        _publish(run, step)

        def make_ctx(
            extra: dict[str, Any] | None = None, *, _node_id: str = node.id
        ) -> NodeContext:
            sc: dict[str, Any] = {
                **outputs,
                "input": run_input,
                "vars": graph.variables,
                "env": env_vars,
                "conv": conv_vars,
                **(extra or {}),
            }
            c = NodeContext(
                run_id=run.id,
                node_id=_node_id,
                run_input=run_input,
                outputs=outputs,
                services=services,
                render=lambda t, s=sc: render(t, s),  # type: ignore[misc]
                render_value=lambda val, s=sc: render_value(val, s),  # type: ignore[misc]
                evaluate=lambda e, s=sc: evaluate(e, s),  # type: ignore[misc]
            )
            base = dict(extra or {})
            c.scoped = lambda more, b=base: _share_logs(make_ctx({**b, **more}), c)
            return c

        ctx = make_ctx()
        retry_cfg = node.data.get("_retry") or {}
        user_retries = int(retry_cfg.get("max_retries") or 0) if isinstance(retry_cfg, dict) else 0
        interval = (
            max(0.1, min(float(retry_cfg.get("interval_ms") or 1000), 5000.0)) / 1000
            if user_retries
            else None
        )
        on_error = str(node.data.get("_on_error") or "stop")
        try:
            if spec is None:
                raise NodeError(
                    f"'{node.type}' 노드를 실행할 수 없어요. 마켓에서 설치했는지 확인하세요."
                )
            result = _run_with_limits(
                spec.run,
                node.data,
                ctx,
                max(spec.retries, min(user_retries, 5)),
                interval,
                retry_all=user_retries > 0,
            )
        except (NodeError, TemplateRenderError) as exc:
            msg = exc.message if isinstance(exc, NodeError) else str(exc)
            if on_error in ("default", "branch"):
                # 실패해도 흐름을 이어 간다: 기본값으로 계속하거나 '실패' 길로 보낸다
                fallback = node.data.get("_default") if on_error == "default" else None
                out = {**(fallback if isinstance(fallback, dict) else {}), "error": msg}
                step.status = "failed"
                step.output = out
                step.logs = "\n".join([*ctx.logs, msg, "실패했지만 설정대로 이어서 진행해요."])
                step.finished_at = now()
                outputs[node.id] = out
                db.commit()
                _publish(run, step)
                current = _next(graph, node.id, "fail" if on_error == "branch" else None)
                continue
            step.status = "failed"
            step.logs = "\n".join([*ctx.logs, msg])
            step.finished_at = now()
            db.commit()
            _finish(db, run, services, "failed", f"[{_label(graph, node.id)}] {msg}")
            return
        except Exception as exc:
            log.exception("노드 실행 오류(run=%s node=%s)", run.id, node.id)
            step.status = "failed"
            step.logs = "\n".join([*ctx.logs, f"예상하지 못한 오류: {type(exc).__name__}"])
            step.finished_at = now()
            db.commit()
            _finish(
                db, run, services, "failed", f"[{_label(graph, node.id)}] 처리 중 문제가 생겼어요."
            )
            return
        step.logs = "\n".join(ctx.logs)
        if result.wait_approval is not None:
            step.status = "waiting_approval"
            run.approval = {
                "node_id": node.id,
                **result.wait_approval,
                "requested_at": now().isoformat(),
            }
            run.context = {"outputs": outputs, "conv": conv_vars}
            run.output = {"text": last_output_text, "outputs": output_values, "conv": conv_vars}
            db.commit()
            _finish(db, run, services, "waiting_approval")
            return
        conv_set = result.output.pop("__conv_set", None)
        if isinstance(conv_set, dict):
            for k, v in conv_set.items():
                if v is None:
                    conv_vars.pop(k, None)
                else:
                    conv_vars[k] = v
        step.status = "succeeded"
        step.output = result.output
        step.finished_at = now()
        outputs[node.id] = result.output
        if node.type == "output":
            last_output_text = str(result.output.get("text", ""))
            output_values[node.id] = result.output
        db.commit()
        _publish(run, step)
        current = _next(graph, node.id, result.handle)

    if not last_output_text and output_values:
        last_output_text = str(list(output_values.values())[-1].get("text", ""))
    run.output = {"text": last_output_text, "outputs": output_values, "conv": conv_vars}
    run.context = {"outputs": outputs, "conv": conv_vars}
    _finish(db, run, services, "succeeded")
