"""SQLite-only test substrate for legacy/reusable unit-style integration tests.

The global runtime remains PostgreSQL-only. Tests that exercise repository or
provider boundaries without PostgreSQL-specific behavior may bind SQLAlchemy
models directly to this isolated engine instead of constructing invalid global
Settings(database_url='sqlite://...').
"""

from pathlib import Path

from sqlalchemy import Engine, create_engine


def create_sqlite_test_engine(path: str | Path) -> Engine:
    return create_engine(f"sqlite+pysqlite:///{Path(path)}")
