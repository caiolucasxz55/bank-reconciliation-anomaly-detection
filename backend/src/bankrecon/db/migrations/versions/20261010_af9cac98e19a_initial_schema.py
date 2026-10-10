"""Initial schema: imported data, pipeline results and import history.

Revision ID: af9cac98e19a
Revises:
Create Date: 2026-10-10 10:19:40.921514

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af9cac98e19a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "imports",
        sa.Column("import_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("imported", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("import_id", name=op.f("pk_imports")),
    )
    op.create_table(
        "suppliers",
        sa.Column("supplier_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_id", sa.String(length=18), nullable=False),
        sa.Column("registered_at", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("supplier_id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("tax_id", name=op.f("uq_suppliers_tax_id")),
    )
    op.create_table(
        "bank_transactions",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["imports.import_id"],
            name=op.f("fk_bank_transactions_import_id_imports"),
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_bank_transactions")),
    )
    op.create_index(op.f("ix_bank_transactions_date"), "bank_transactions", ["date"], unique=False)

    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.String(length=64), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("supplier_id", sa.String(length=32), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_id"], ["imports.import_id"], name=op.f("fk_invoices_import_id_imports")
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.supplier_id"],
            name=op.f("fk_invoices_supplier_id_suppliers"),
        ),
        sa.PrimaryKeyConstraint("invoice_id", name=op.f("pk_invoices")),
    )
    op.create_index(op.f("ix_invoices_supplier_id"), "invoices", ["supplier_id"], unique=False)

    op.create_table(
        "anomaly_scores",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("percentile", sa.Double(), nullable=False),
        sa.Column("rank_label", sa.String(length=64), nullable=False),
        sa.Column("high_risk", sa.Boolean(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["bank_transactions.transaction_id"],
            name=op.f("fk_anomaly_scores_transaction_id_bank_transactions"),
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_anomaly_scores")),
    )
    op.create_index(
        op.f("ix_anomaly_scores_high_risk"), "anomaly_scores", ["high_risk"], unique=False
    )
    op.create_index(op.f("ix_anomaly_scores_rank"), "anomaly_scores", ["rank"], unique=False)

    op.create_table(
        "matches",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("layer", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("supplier_id", sa.String(length=32), nullable=True),
        sa.Column("decided_by", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.supplier_id"],
            name=op.f("fk_matches_supplier_id_suppliers"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["bank_transactions.transaction_id"],
            name=op.f("fk_matches_transaction_id_bank_transactions"),
        ),
        sa.PrimaryKeyConstraint("transaction_id", name=op.f("pk_matches")),
    )
    op.create_index(op.f("ix_matches_status"), "matches", ["status"], unique=False)

    op.create_table(
        "match_invoices",
        sa.Column("transaction_id", sa.String(length=64), nullable=False),
        sa.Column("invoice_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.invoice_id"],
            name=op.f("fk_match_invoices_invoice_id_invoices"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["matches.transaction_id"],
            name=op.f("fk_match_invoices_transaction_id_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("transaction_id", "invoice_id", name=op.f("pk_match_invoices")),
        sa.UniqueConstraint("invoice_id", name=op.f("uq_match_invoices_invoice_id")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("match_invoices")
    op.drop_index(op.f("ix_matches_status"), table_name="matches")

    op.drop_table("matches")
    op.drop_index(op.f("ix_anomaly_scores_rank"), table_name="anomaly_scores")
    op.drop_index(op.f("ix_anomaly_scores_high_risk"), table_name="anomaly_scores")

    op.drop_table("anomaly_scores")
    op.drop_index(op.f("ix_invoices_supplier_id"), table_name="invoices")

    op.drop_table("invoices")
    op.drop_index(op.f("ix_bank_transactions_date"), table_name="bank_transactions")

    op.drop_table("bank_transactions")
    op.drop_table("suppliers")
    op.drop_table("imports")
