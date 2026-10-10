import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from bankrecon.db.migrate import MigrationError, UnversionedDatabaseError, upgrade
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
