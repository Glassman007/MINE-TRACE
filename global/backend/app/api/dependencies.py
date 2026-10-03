"""Transport-level dependency helpers."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.repositories.unit_of_work import SQLAlchemyUnitOfWork, UnitOfWork


def uow_factory_for_session(session: Session) -> Callable[[], UnitOfWork]:
    return lambda: SQLAlchemyUnitOfWork(lambda: session, close_session=False)
