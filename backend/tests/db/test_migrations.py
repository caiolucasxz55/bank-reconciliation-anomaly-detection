import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from bankrecon.db.migrate import (
    MigrationError,
    UnversionedDatabaseError,
    alembic_config,
    upgrade,
)
from bankrecon.db.models import Base
from bankrecon.db.session import make_engine


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    yield engine
    engine.dispose()


def test_migrations_produce_exactly_the_models_schema(engine):
    """Fails when a model changes without a matching migration."""
    upgrade(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_upgrade_is_idempotent(engine):
    upgrade(engine)
    upgrade(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"alembic_version", "bank_transactions", "imports", "suppliers"} <= tables


def test_database_created_without_migrations_is_rejected(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE bank_transactions (transaction_id TEXT)"))
    with pytest.raises(UnversionedDatabaseError, match="docker compose down -v"):
        upgrade(engine)


def test_unknown_revision_is_reported_as_a_migration_error(engine):
    upgrade(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'from_the_future'"))
    with pytest.raises(MigrationError, match="falha ao migrar"):
        upgrade(engine)


def test_unversioned_database_is_a_migration_error():
    assert issubclass(UnversionedDatabaseError, MigrationError)


KEY = "35250345997418000153550010000012341123456789"


def test_nfe_access_key_ids_are_renamed_and_merged(engine):
    config = alembic_config(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0860f2c1b18e")  # schema before the id change
        connection.execute(
            text(
                "INSERT INTO suppliers VALUES ('45997418000153', 'Acme', "
                "'45.997.418/0001-53', '2025-03-05')"
            )
        )
        invoice = (
            "INSERT INTO invoices (invoice_id, number, supplier_id, issue_date, due_date, "
            "amount) VALUES (:id, '1234/001', '45997418000153', '2025-03-05', "
            "'2025-04-05', 1500)"
        )
        connection.execute(text(invoice), {"id": f"{KEY}-001"})
        connection.execute(text(invoice), {"id": f"{KEY}-002"})
        # The same installment 002 also came from a spreadsheet, under the new id.
        connection.execute(text(invoice), {"id": "45997418000153-1234-2"})
        connection.execute(
            text("INSERT INTO bank_transactions VALUES ('TX1', '2025-04-07', 1500, 'PIX', NULL)")
        )
        connection.execute(
            text(
                "INSERT INTO matches VALUES ('TX1', 'conciliada', 1, 1.0, '45997418000153', "
                "'sistema', NULL)"
            )
        )
        connection.execute(text(f"INSERT INTO match_invoices VALUES ('TX1', '{KEY}-001')"))

    upgrade(engine)

    with engine.connect() as connection:
        ids = connection.execute(text("SELECT invoice_id FROM invoices ORDER BY 1")).scalars()
        assert list(ids) == ["45997418000153-1234-1", "45997418000153-1234-2"]
        link = connection.execute(text("SELECT invoice_id FROM match_invoices")).scalar_one()
        assert link == "45997418000153-1234-1"
