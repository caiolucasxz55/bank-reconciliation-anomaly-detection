"""Schema migrations (Alembic), run programmatically by the CLI and the API on startup."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError as AlembicCommandError
from sqlalchemy import Connection, Engine, inspect, text

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
VERSION_TABLE = "alembic_version"
# Arbitrary constant identifying this app's migration lock in Postgres.
POSTGRES_MIGRATION_LOCK_ID = 7_204_118_301


class MigrationError(RuntimeError):
    """The database schema could not be brought up to date."""


class UnversionedDatabaseError(MigrationError):
    """The database has tables but no migration history (created before migrations)."""

    def __init__(self) -> None:
        super().__init__(
            "o banco foi criado por uma versão anterior, sem controle de migrações; "
            "recrie-o (com Docker: docker compose down -v) e carregue os dados de novo"
        )


def alembic_config(engine: Engine | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if engine is not None:
        # "%" must be escaped in Alembic options (passwords may contain it).
        url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
        config.set_main_option("sqlalchemy.url", url)
    return config


def _lock(connection: Connection) -> None:
    """Serialize concurrent upgrades (several workers or replicas starting at once).

    Postgres gets a transaction-scoped advisory lock. SQLite needs nothing more: its
    write transaction (DDL is transactional, see session.make_engine) locks the file.
    """
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:id)"), {"id": POSTGRES_MIGRATION_LOCK_ID}
        )


def upgrade(engine: Engine) -> None:
    """Bring the database to the latest schema version, atomically."""
    config = alembic_config(engine)
    try:
        with engine.begin() as connection:
            _lock(connection)
            tables = set(inspect(connection).get_table_names())
            if tables and VERSION_TABLE not in tables:
                raise UnversionedDatabaseError
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except AlembicCommandError as error:
        # e.g. the database is at a revision this (older) code does not know.
        raise MigrationError(f"falha ao migrar o banco: {error}") from error
