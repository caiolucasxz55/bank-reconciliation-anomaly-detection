"""Alembic environment.

The database comes from the Alembic config (set by ``bankrecon.db.migrate``) or, when
Alembic is run by hand from ``backend/``, from ``$DATABASE_URL`` / the default SQLite file.
A connection can also be handed over through ``config.attributes["connection"]``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from bankrecon.db.models import Base
from bankrecon.db.session import database_url, make_engine

config = context.config
target_metadata = Base.metadata


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
        url=config.get_main_option("sqlalchemy.url") or database_url(),
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
    engine = make_engine(config.get_main_option("sqlalchemy.url") or database_url())
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
