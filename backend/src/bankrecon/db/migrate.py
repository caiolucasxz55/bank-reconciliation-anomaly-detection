"""Schema migrations (Alembic), run programmatically by the CLI and the API on startup."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
VERSION_TABLE = "alembic_version"


class UnversionedDatabaseError(RuntimeError):
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


def upgrade(engine: Engine) -> None:
    """Bring the database to the latest schema version."""
    tables = set(inspect(engine).get_table_names())
    if tables and VERSION_TABLE not in tables:
        raise UnversionedDatabaseError
    config = alembic_config(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
