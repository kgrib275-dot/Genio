"""FastAPI 진입점. 업무 API는 /api/v1 아래에 둔다."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.config import get_settings
from api.core.errors import install_error_handlers
from api.db import Base, SessionLocal, engine
from api.market.service import ensure_market_nodes, sync_catalog
from api.routers import (
    account,
    admin,
    apps,
    apps_v02,
    auth,
    builder,
    connectors,
    data_tables,
    deployments,
    hooks,
    knowledge,
    knowledge_v08,
    market,
    mcp,
    onboarding,
    ops,
    projects,
    runs,
    samples,
    service,
    share_meta,
    tasks,
    tracing,
    triggers,
    versions_v06,
    workspaces,
)
from api.services.seed import seed_demo, seed_demo_samples

logging.basicConfig(level=get_settings().genio_log_level)
log = logging.getLogger("genio")


def startup() -> None:
    if engine.dialect.name == "sqlite":
        # 로컬·테스트용. PostgreSQL은 Alembic 마이그레이션으로만 바꾼다.
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if engine.dialect.name == "postgresql":
            # API 프로세스가 여러 개면 동시에 시작한다. 마켓 동기화·데모 준비는 한 번에 하나씩.
            db.execute(text("select pg_advisory_lock(7412001)"))
        try:
            count = sync_catalog(db)
            log.info("마켓 아이템 %d개 동기화", count)
            if get_settings().genio_seed_demo:
                seed_demo(db)
                seed_demo_samples(db)
            ensure_market_nodes(db)
        finally:
            if engine.dialect.name == "postgresql":
                db.rollback()
                db.execute(text("select pg_advisory_unlock(7412001)"))
                db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 동기 엔드포인트·스트리밍 응답이 쓰는 작업 스레드 수(기본 40). 공개 챗은 답을 기다리는 동안
    # 스레드를 하나 쓰므로 넉넉히 둔다. DB 연결은 위에서 짧게만 쓰므로 스레드보다 적어도 된다.
    to_thread.current_default_thread_limiter().total_tokens = get_settings().genio_api_threads
    startup()
    yield


app = FastAPI(title="Genio API", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)


def _cors_origins() -> list[str]:
    """API를 부를 수 있는 브라우저 주소: 공개 웹 주소 + GENIO_CORS_ORIGINS(남의 *.ts.net은 막음)."""
    st = get_settings()
    out = [st.genio_public_web_url.rstrip("/")]
    out += [o.strip().rstrip("/") for o in st.genio_cors_origins.split(",") if o.strip()]
    return [o for o in dict.fromkeys(out) if o]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
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
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


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
    runs,
    builder,
    knowledge,
    knowledge_v08,
    deployments,
    hooks,
    market,
    onboarding,
    projects,
    samples,
    service,
    share_meta,
    mcp,
    ops,
    tasks,
    tracing,
    triggers,
    versions_v06,
):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().genio_env}
