"""FastAPI 진입점. 업무 API는 /api/v1 아래에 둔다."""

import hmac
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from anyio import to_thread
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from api.config import get_settings, is_production
from api.core.errors import install_error_handlers
from api.core.observability import observe_request, render_metrics, request_id_var, setup_logging
from api.core.sentry import init_sentry
from api.db import Base, SessionLocal, engine
from api.deps import public_ip_guard
from api.market.service import ensure_market_nodes, sync_catalog
from api.routers import (
    account,
    admin,
    announcements,
    apidocs,
    apps,
    apps_v02,
    attention,
    auth,
    batches,
    builder,
    collab,
    connectors,
    data_tables,
    dependencies,
    deployments,
    dify_import,
    digest,
    doc_bot,
    evals,
    external_tools,
    hooks,
    hub,
    improvements,
    instance_overview,
    kb_image_files,
    knowledge,
    knowledge_v08,
    llm_v09,
    market,
    mcp,
    messenger,
    onboarding,
    ops,
    ownership,
    projects,
    run_files,
    runs,
    samples,
    search,
    service,
    service_events,
    share_meta,
    skills,
    snippets,
    tasks,
    team_templates,
    tracing,
    triggers,
    versions_v06,
    workspace_export,
    workspaces,
)
from api.services.seed import seed_demo, seed_demo_samples


def _utc_isoformat(dt: datetime) -> str:
    """시간대 표시가 없는 시각(개발용 sqlite가 돌려줌)은 UTC로 보고 +00:00을 붙인다.
    안 붙이면 브라우저가 내 시간대로 읽어서 '9시간 전'처럼 어긋난다. 운영 DB(PostgreSQL)는 원래 붙어 있다."""
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


ENCODERS_BY_TYPE[datetime] = _utc_isoformat


setup_logging("api")  # 운영 준비 1차(A6): GENIO_LOG_FORMAT=json이면 JSON 한 줄 로그
log = logging.getLogger("genio")
init_sentry("api")  # SENTRY_DSN이 있을 때만 켜진다(v0.8)


def startup() -> None:
    if engine.dialect.name == "sqlite":
        # 로컬·테스트용. PostgreSQL은 Alembic 마이그레이션으로만 바꾼다.
        Base.metadata.create_all(engine)
    lock_conn = None
    if engine.dialect.name == "postgresql":
        # API 프로세스가 여러 개면 동시에 시작한다. 마켓 동기화·데모 준비는 한 번에 하나씩.
        # 잠금은 전용 연결 하나에서 잡고 같은 연결에서 풀어야 한다(풀 연결이 바뀌면 안 풀린다).
        lock_conn = engine.connect()
        lock_conn.execute(text("select pg_advisory_lock(7412001)"))
    with SessionLocal() as db:
        try:
            count = sync_catalog(db)
            log.info("마켓 아이템 %d개 동기화", count)
            from api.config import is_production

            if get_settings().genio_seed_demo and not is_production(get_settings()):
                seed_demo(db)
                seed_demo_samples(db)
            ensure_market_nodes(db)
        finally:
            if lock_conn is not None:
                try:
                    lock_conn.execute(text("select pg_advisory_unlock(7412001)"))
                finally:
                    lock_conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 동기 엔드포인트·스트리밍 응답이 쓰는 작업 스레드 수(기본 40). 공개 챗은 답을 기다리는 동안
    # 스레드를 하나 쓰므로 넉넉히 둔다. DB 연결은 위에서 짧게만 쓰므로 스레드보다 적어도 된다.
    to_thread.current_default_thread_limiter().total_tokens = get_settings().genio_api_threads
    check_secret_key()
    startup()
    yield


def check_secret_key() -> None:
    """운영 준비 1차(B1·F20): 운영 모드(GENIO_ENV=production)에서 기본·짧은 비밀 키면 기동을 멈춘다.
    개발 모드에서는 경고만 남기고, 관리 > 시스템 상태에 '주의'로 보인다."""
    from api.config import fernet_key_problem, is_production, secret_key_problem

    st = get_settings()
    problems = [p for p in (secret_key_problem(st), fernet_key_problem(st)) if p]
    if not problems:
        return
    if is_production(st):
        raise RuntimeError(
            "; ".join(problems)
            + ". .env의 GENIO_SECRET_KEY·GENIO_FERNET_KEY를 긴 무작위 값으로 채운 뒤 다시 시작하세요."
        )
    for problem in problems:
        logging.getLogger("genio").warning("%s. 운영 전에 바꾸세요.", problem)


app = FastAPI(
    title="Genio API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(public_ip_guard)],
)
install_error_handlers(app)


def _cors_origins() -> list[str]:
    """API를 부를 수 있는 브라우저 주소: 공개 웹 주소 + GENIO_CORS_ORIGINS(남의 *.ts.net은 막음)."""
    st = get_settings()
    out = [st.genio_public_web_url.rstrip("/")]
    out += [o.strip().rstrip("/") for o in st.genio_cors_origins.split(",") if o.strip()]
    return [o for o in dict.fromkeys(out) if o]


def _cors_origin_regex() -> str | None:
    """개발 중에만 localhost를 허용한다(운영에서는 공개 웹 주소와 GENIO_CORS_ORIGINS만)."""
    if is_production(get_settings()):
        return None
    return r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _request_id(request: Request, call_next: Any) -> Any:
    """요청마다 번호(X-Request-ID)를 붙인다. 오류 화면·서버 오류 기록에서 같은 번호로 찾는다."""
    from api.services.error_log import clean_request_id

    rid = clean_request_id(request.headers.get("x-request-id"))
    request.state.request_id = rid
    token = request_id_var.set(rid)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    finally:
        request_id_var.reset(token)
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "(없는 주소)"
        if path != "/metrics":
            observe_request(request.method, path, status, time.perf_counter() - started)
    response.headers["X-Request-ID"] = rid
    return response


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """운영 준비 1차(A6): Prometheus 지표. GENIO_METRICS_TOKEN을 정해야 켜지고 Bearer 토큰이 맞아야 한다.
    사람이 쓰는 주소가 아니라 수집기용이라 역할(require_role) 대신 토큰으로 지킨다."""
    expected = get_settings().genio_metrics_token
    if not expected:
        return Response(status_code=404)
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return Response(render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.middleware("http")
async def _reject_nul(request: Request, call_next: Any) -> Any:
    """주소의 검색어 등에 NUL 문자(%00)가 있으면 DB 오류(500) 대신 400으로 막는다."""
    if "%00" in request.url.query or "%00" in request.url.path:
        return JSONResponse(
            status_code=400,
            content={
                "detail": {
                    "message": "주소에 쓸 수 없는 글자가 들어 있어요.",
                    "hint": "검색어에서 보이지 않는 특수 문자를 지우고 다시 시도하세요.",
                }
            },
        )
    return await call_next(request)


for r in (
    account,
    admin,
    auth,
    workspaces,
    connectors,
    data_tables,
    apps,
    apps_v02,
    batches,
    collab,
    run_files,
    runs,
    builder,
    knowledge,
    llm_v09,
    kb_image_files,
    knowledge_v08,
    deployments,
    external_tools,
    dify_import,
    hooks,
    market,
    onboarding,
    projects,
    samples,
    search,
    service,
    service_events,
    share_meta,
    snippets,
    evals,
    hub,
    announcements,
    attention,
    improvements,
    skills,
    dependencies,
    digest,
    workspace_export,
    team_templates,
    instance_overview,
    doc_bot,
    apidocs,
    mcp,
    messenger,
    ops,
    ownership,
    tasks,
    tracing,
    triggers,
    versions_v06,
):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().genio_env}
