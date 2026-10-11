"""NF-e access key ids to payable ids (CNPJ + series + number + installment).

Invoices imported from NF-e XML used to be stored under their 44-digit access key
(``<key>`` or ``<key>-<installment>``). They now share the format-independent id of
spreadsheet imports, so the same invoice is never stored twice. This migration renames the
old rows; when the new id already exists (the same invoice came from a spreadsheet too),
the old row is merged into it.

The id rules are copied here on purpose: a migration must keep doing what it did when it
was written, whatever happens to the application code later.

Revision ID: 842534bf452d
Revises: 0860f2c1b18e
Create Date: 2026-10-11 14:40:05.186713

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "842534bf452d"
down_revision: str | Sequence[str] | None = "0860f2c1b18e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ID = re.compile(r"^(\d{44})(?:-(.+))?$")
_DEFAULT_SERIES = {"", "0", "1"}


def _canonical(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[\d.\s/-]+", value) and (digits := re.sub(r"\D", "", value)):
        return digits.lstrip("0") or "0"
    return value


def _new_id(access_key: str, installment: str | None) -> str:
    # Access key layout: UF(2) AAMM(4) CNPJ(14) model(2) series(3) number(9) ...
    cnpj, series, number = access_key[6:20], access_key[22:25], access_key[25:34]
    parts = [cnpj]
    if (series := _canonical(series)) not in _DEFAULT_SERIES:
        parts.append(f"s{series}")
    parts.append(_canonical(number))
    if installment:
        parts.append(_canonical(installment))
    return "-".join(parts)


def upgrade() -> None:
    connection = op.get_bind()
    invoices = sa.table(
        "invoices",
        sa.column("invoice_id", sa.String),
        sa.column("number", sa.String),
        sa.column("supplier_id", sa.String),
        sa.column("issue_date", sa.Date),
        sa.column("due_date", sa.Date),
        sa.column("amount", sa.Numeric(14, 2)),
        sa.column("import_id", sa.Integer),
    )
    links = sa.table(
        "match_invoices",
        sa.column("transaction_id", sa.String),
        sa.column("invoice_id", sa.String),
    )
    rows = connection.execute(sa.select(invoices)).mappings().all()
    existing = {row["invoice_id"] for row in rows}
    for row in rows:
        match = _OLD_ID.match(row["invoice_id"])
        if match is None:
            continue
        old_id, new_id = row["invoice_id"], _new_id(match.group(1), match.group(2))
        if new_id not in existing:
            connection.execute(sa.insert(invoices).values({**row, "invoice_id": new_id}))
            existing.add(new_id)
        already_linked = connection.execute(
            sa.select(links.c.transaction_id).where(links.c.invoice_id == new_id)
        ).first()
        if already_linked:
            # The merged copy is settled already; the old row's link would duplicate it.
            connection.execute(sa.delete(links).where(links.c.invoice_id == old_id))
        else:
            connection.execute(
                sa.update(links).where(links.c.invoice_id == old_id).values(invoice_id=new_id)
            )
        connection.execute(sa.delete(invoices).where(invoices.c.invoice_id == old_id))


def downgrade() -> None:
    # The access key cannot be rebuilt from the new id; the rename is kept.
    pass
