from collections.abc import Callable, Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings

EngineFactory = Callable[..., Engine]


def create_database_engine(
    settings: Settings,
    *,
    engine_factory: EngineFactory = create_engine,
) -> Engine:
    """Create the canonical PostgreSQL SQLAlchemy engine.

    The settings layer rejects non-PostgreSQL URLs, so there are deliberately no
    SQLite branches, PRAGMAs or SQLite connection arguments here.
    """

    return engine_factory(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # Lazy creation keeps import/CLI inspection independent from an immediately
    # reachable database while still requiring the psycopg runtime driver when a
    # database connection is actually needed.
    return create_database_engine(get_settings())


def SessionLocal() -> Session:
    """Return one unshared session bound to the canonical PostgreSQL engine."""

    return Session(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding one safely-closed PostgreSQL session."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
