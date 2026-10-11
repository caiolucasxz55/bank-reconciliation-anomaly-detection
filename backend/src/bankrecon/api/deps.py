"""Request dependencies shared by the routers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Writes commit explicitly *before* the response is built
    (dependency teardown runs after the response is sent); anything uncommitted is
    rolled back when the session closes."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
