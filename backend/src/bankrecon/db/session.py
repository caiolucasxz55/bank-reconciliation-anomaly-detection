"""Engine and session factory configuration."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bankrecon.db.migrate import upgrade

DEFAULT_DATA_DIR = Path("data")
SQLITE_FILE = "bankrecon.db"


def sqlite_url(data_dir: Path) -> str:
    """Absolute SQLite URL inside ``data_dir``, so it does not depend on the working dir."""
    return f"sqlite:///{(data_dir / SQLITE_FILE).resolve().as_posix()}"


def database_url(data_dir: Path | None = None) -> str:
    """``$DATABASE_URL``, else a SQLite file in ``data_dir`` (default ``$BANKRECON_DATA_DIR``
    or ``./data``). The CLI and the API resolve the default the same way."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    if data_dir is None:
        data_dir = Path(os.environ.get("BANKRECON_DATA_DIR", DEFAULT_DATA_DIR))
    return sqlite_url(data_dir)


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)

    options: dict = {"connect_args": {"check_same_thread": False}}
    database = make_url(url).database
    if database in (None, "", ":memory:"):
        # One shared connection keeps an in-memory database alive across sessions.
        options["poolclass"] = StaticPool
    else:
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **options)
    # SQLite ignores foreign keys unless asked to enforce them.
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def create_schema(engine: Engine) -> None:
    """Apply every pending migration (Alembic), creating the tables on a new database."""
    upgrade(engine)
