"""Alembic environment.

The app runs migrations through ``bankrecon.db.migrate``, which hands over a connection in
``config.attributes["connection"]``. When Alembic is run by hand from ``backend/`` (to
autogenerate a revision), the database is ``$DATABASE_URL`` or the app's default SQLite file
in the repository's ``data/`` directory (or ``$BANKRECON_DATA_DIR``).
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection

from bankrecon.db.models import Base
from bankrecon.db.session import database_url, make_engine

config = context.config
target_metadata = Base.metadata
# migrations -> db -> bankrecon -> src -> backend -> repository root
REPOSITORY_DATA_DIR = Path(__file__).resolve().parents[5] / "data"

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url() -> str:
    if url := config.get_main_option("sqlalchemy.url"):
        return url
    return database_url(Path(os.environ.get("BANKRECON_DATA_DIR", REPOSITORY_DATA_DIR)))


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place; batch mode recreates tables instead.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(_url())
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
