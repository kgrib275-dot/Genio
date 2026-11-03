"""DB 엔진·세션. 운영은 PostgreSQL, 단위 테스트는 SQLite를 쓴다."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import JSON, Text, create_engine, event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeEngine

from api.config import get_settings

# PostgreSQL 전용 타입을 SQLite에서도 쓸 수 있게 변형한다.
JsonType: TypeEngine[Any] = JSONB().with_variant(JSON(), "sqlite")
TextArray: TypeEngine[Any] = ARRAY(Text()).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        eng = create_engine(url, **kwargs)

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn: Any, _: Any) -> None:
            # PostgreSQL처럼 외래 키 제약을 지키게 한다(삭제 순서 버그를 테스트에서 잡기 위해)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    s = get_settings()
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=s.genio_db_pool_size,
        max_overflow=s.genio_db_max_overflow,
        pool_timeout=15,
    )


engine: Engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_engine(url: str) -> Engine:
    """테스트에서 DB를 바꿀 때 쓴다."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)
    return engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"
