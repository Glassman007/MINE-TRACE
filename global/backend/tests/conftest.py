from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_db_session
from tests.sqlite_test_db import create_sqlite_test_engine
from app.main import app


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    test_engine = create_sqlite_test_engine(tmp_path / 'test.db')
    test_session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    def override_get_db_session() -> Generator[Session, None, None]:
        session = test_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()
