"""Engine and session factory configuration."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bankrecon.db.models import Base

DEFAULT_DATABASE_URL = "sqlite:///data/bankrecon.db"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith("sqlite"):
        options: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection keeps an in-memory database alive across sessions.
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)
        # SQLite ignores foreign keys unless asked to enforce them.
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Create missing tables. The MVP has a single schema version, so no migrations yet."""
    Base.metadata.create_all(engine)
