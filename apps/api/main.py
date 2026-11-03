"""FastAPI 진입점. 업무 API는 /api/v1 아래에 둔다."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.core.errors import install_error_handlers
from api.db import Base, SessionLocal, engine
from api.market.service import ensure_market_nodes, sync_catalog
from api.routers import (
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
    market,
    projects,
    runs,
    service,
    triggers,
    workspaces,
)
from api.services.seed import seed_demo

logging.basicConfig(level=get_settings().genio_log_level)
log = logging.getLogger("genio")


def startup() -> None:
    if engine.dialect.name == "sqlite":
        # 로컬·테스트용. PostgreSQL은 Alembic 마이그레이션으로만 바꾼다.
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        count = sync_catalog(db)
        log.info("마켓 아이템 %d개 동기화", count)
        if get_settings().genio_seed_demo:
            seed_demo(db)
        ensure_market_nodes(db)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    startup()
    yield


app = FastAPI(title="Genio API", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
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
    deployments,
    hooks,
    market,
    projects,
    service,
    triggers,
):
    app.include_router(r.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().genio_env}
