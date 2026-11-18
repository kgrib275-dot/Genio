"""관측(운영 준비 1차 A6): 구조화 로그(JSON)와 Prometheus 지표.

로그
  GENIO_LOG_FORMAT=json 이면 한 줄에 JSON 하나(ts·level·logger·msg·request_id). 비밀값은 error_log.redact로 가린다.
  요청 번호는 contextvar로 들고 다녀서 그 요청 중에 남긴 모든 로그에 붙는다.
지표
  GET /metrics (Prometheus 글 형식). GENIO_METRICS_TOKEN을 정해야 켜지고, 'Authorization: Bearer <토큰>'이 맞아야 답한다.
  API 프로세스가 여럿이라 요청 수·응답 시간은 Redis에 함께 센다(키 genio:m:*). Redis가 없으면 프로세스 메모리.
  실행·대기열·AI 비용 같은 값은 긁어 갈 때 DB·Redis에서 바로 읽는다.
새 라이브러리 없이(prometheus_client 없이) 글 형식을 직접 만든다. 이미지를 다시 빌드하지 않아도 된다.
"""

import contextlib
import contextvars
import json
import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import redis

from api.config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("genio_request_id", default="")

# 응답 시간 구간(초)
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_PREFIX = "genio:m:"


# ---------------- 로그 ----------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from api.services.error_log import redact

        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else ""
            out["exc"] = redact(self.formatException(record.exc_info))[-4000:]
        return json.dumps(out, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    """글 형식 로그에도 요청 번호를 붙인다([rid] 꼴)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def setup_logging(service: str = "api") -> None:
    st = get_settings()
    root = logging.getLogger()
    root.setLevel(st.genio_log_level)
    handler = logging.StreamHandler()
    if st.genio_log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s:%(name)s:[%(request_id)s] %(message)s")
        )
        handler.addFilter(RequestIdFilter())
    root.handlers = [handler]
    logging.getLogger("genio").debug("로그 형식: %s (%s)", st.genio_log_format, service)


# ---------------- 지표 저장(요청) ----------------
_lock = threading.Lock()
_mem: dict[str, float] = defaultdict(float)


@lru_cache
def _redis() -> "redis.Redis[bytes] | None":
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(url, socket_timeout=0.3, socket_connect_timeout=0.3)


_skip_until = [0.0]


def _bump(fields: dict[str, float]) -> None:
    client = _redis()
    if client is not None and time.time() >= _skip_until[0]:
        try:
            pipe = client.pipeline(transaction=False)
            for k, v in fields.items():
                pipe.hincrbyfloat(_PREFIX + "http", k, v)
            pipe.execute()
            return
        except redis.RedisError:
            _skip_until[0] = time.time() + 10
    with _lock:
        for k, v in fields.items():
            _mem[k] += v


def status_class(code: int) -> str:
    return f"{code // 100}xx"


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    """요청 하나를 센다. route는 주소 틀(/api/v1/apps/{app_id})이라 값 종류가 늘지 않는다."""
    labels = f"{method}|{route}|{status_class(status)}"
    fields: dict[str, float] = {f"count|{labels}": 1.0, "dur_sum": seconds, "dur_count": 1.0}
    for b in BUCKETS:
        if seconds <= b:
            fields[f"bucket|{b}"] = 1.0
    _bump(fields)


def _read_http() -> dict[str, float]:
    client = _redis()
    if client is not None:
        try:
            raw = client.hgetall(_PREFIX + "http")
            return {k.decode(): float(v) for k, v in raw.items()}
        except redis.RedisError:
            pass
    with _lock:
        return dict(_mem)


def reset() -> None:
    with _lock:
        _mem.clear()
    client = _redis()
    if client is not None:
        with contextlib.suppress(redis.RedisError):
            client.delete(_PREFIX + "http")


# ---------------- 글 형식 ----------------
def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        inner = ",".join(f'{k}="{_esc(str(v))}"' for k, v in labels.items())
        return f"{name}{{{inner}}} {value:g}"
    return f"{name} {value:g}"


def _http_lines(data: dict[str, float]) -> list[str]:
    out = [
        "# HELP genio_http_requests_total API 요청 수(주소 틀·방식·응답 종류별)",
        "# TYPE genio_http_requests_total counter",
    ]
    for k, v in sorted(data.items()):
        if k.startswith("count|"):
            _, method, route, cls = k.split("|", 3)
            out.append(
                _line(
                    "genio_http_requests_total",
                    v,
                    {"method": method, "route": route, "status": cls},
                )
            )
    out += [
        "# HELP genio_http_request_duration_seconds API 응답 시간",
        "# TYPE genio_http_request_duration_seconds histogram",
    ]
    for b in BUCKETS:
        out.append(
            _line(
                "genio_http_request_duration_seconds_bucket",
                data.get(f"bucket|{b}", 0.0),
                {"le": f"{b:g}"},
            )
        )
    total = data.get("dur_count", 0.0)
    out.append(_line("genio_http_request_duration_seconds_bucket", total, {"le": "+Inf"}))
    out.append(_line("genio_http_request_duration_seconds_sum", data.get("dur_sum", 0.0)))
    out.append(_line("genio_http_request_duration_seconds_count", total))
    return out


def _app_lines() -> list[str]:
    """긁어 갈 때 DB·Redis에서 바로 읽는 값(게이지)."""
    from sqlalchemy import func, select

    from api.db import SessionLocal
    from api.models import Run, User, Workspace
    from api.services.limits import month_start

    out: list[str] = []
    now = datetime.now(UTC)
    with SessionLocal() as db:
        rows = db.execute(
            select(Run.status, func.count())
            .where(Run.created_at >= now - timedelta(hours=24))
            .group_by(Run.status)
        ).all()
        out += [
            "# HELP genio_runs_24h 최근 24시간 실행 수(상태별)",
            "# TYPE genio_runs_24h gauge",
        ]
        for status, n in rows:
            out.append(_line("genio_runs_24h", float(n), {"status": str(status)}))
        running = db.scalar(select(func.count()).select_from(Run).where(Run.status == "running"))
        cost = db.scalar(
            select(func.coalesce(func.sum(Run.cost), 0)).where(Run.created_at >= month_start(now))
        )
        tokens = db.execute(
            select(Run.token_usage).where(Run.created_at >= now - timedelta(hours=24))
        ).all()
        tin = sum(int((t or {}).get("input_tokens", 0) or 0) for (t,) in tokens)
        tout = sum(int((t or {}).get("output_tokens", 0) or 0) for (t,) in tokens)
        out += [
            "# TYPE genio_runs_running gauge",
            _line("genio_runs_running", float(running or 0)),
            "# HELP genio_ai_cost_usd_month 이번 달 AI 비용(달러, 모든 워크스페이스)",
            "# TYPE genio_ai_cost_usd_month gauge",
            _line("genio_ai_cost_usd_month", float(cost or 0)),
            "# HELP genio_ai_tokens_24h 최근 24시간 AI 토큰",
            "# TYPE genio_ai_tokens_24h gauge",
            _line("genio_ai_tokens_24h", float(tin), {"kind": "input"}),
            _line("genio_ai_tokens_24h", float(tout), {"kind": "output"}),
            "# TYPE genio_users gauge",
            _line("genio_users", float(db.scalar(select(func.count()).select_from(User)) or 0)),
            "# TYPE genio_workspaces gauge",
            _line(
                "genio_workspaces",
                float(db.scalar(select(func.count()).select_from(Workspace)) or 0),
            ),
        ]
    out += _queue_lines()
    return out


def _queue_lines() -> list[str]:
    st = get_settings()
    url = st.celery_broker_url or st.redis_url
    out: list[str] = []
    if url.startswith("redis"):
        try:
            r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
            out += [
                "# HELP genio_queue_length 실행을 기다리는 작업 수",
                "# TYPE genio_queue_length gauge",
                _line("genio_queue_length", float(r.llen("celery"))),
            ]
        except redis.RedisError:
            pass
    client = _redis()
    if client is not None:
        try:
            raw = client.get("genio:beat:last:dispatch_schedules")
            if raw:
                out += [
                    "# HELP genio_scheduler_last_run_seconds 예약 확인이 마지막으로 돈 뒤 지난 초",
                    "# TYPE genio_scheduler_last_run_seconds gauge",
                    _line("genio_scheduler_last_run_seconds", time.time() - int(raw)),
                ]
        except (redis.RedisError, ValueError):
            pass
    return out


def render_metrics() -> str:
    lines = _http_lines(_read_http())
    try:
        lines += _app_lines()
        lines.append(_line("genio_metrics_db_up", 1.0))
    except Exception:
        logging.getLogger("genio.metrics").warning("지표용 DB 읽기 실패")
        lines.append(_line("genio_metrics_db_up", 0.0))
    return "\n".join(lines) + "\n"
