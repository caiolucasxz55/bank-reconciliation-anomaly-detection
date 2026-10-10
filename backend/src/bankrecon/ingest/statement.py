"""Bank statement readers: OFX (SGML 1.x and XML 2.x) and CSV.

Every line gets an ``external_id`` that is the same whenever the same transaction is
imported again (even from a statement covering a different period), so reimports are
recognized as duplicates. Ids are scoped by account: OFX files name their accounts; CSV
files do not, so the caller passes an account label.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bankrecon.ingest.common import (
    ParseError,
    ParseResult,
    clean_description,
    decode,
    parse_amount,
    parse_date,
    read_csv,
    short_hash,
)

DEFAULT_ACCOUNT = "conta"


@dataclass(frozen=True)
class StatementLine:
    external_id: str
    date: date
    # Signed as in the statement: negative = money out (a payment).
    amount: Decimal
    description: str


class _Occurrences:
    """Numbers identical lines 1, 2, 3... so two equal payments on a day stay distinct,
    while the numbering does not depend on where the lines sit in the file."""

    def __init__(self) -> None:
        self._seen: Counter[tuple] = Counter()

    def next(self, *key: object) -> int:
        self._seen[key] += 1
        return self._seen[key]


# -- OFX ----------------------------------------------------------------------------------

# One statement per account: bank (STMTRS) or credit card (CCSTMTRS).
_STATEMENT = re.compile(
    r"<(CC)?STMTRS>(.*?)(?:</(?:CC)?STMTRS>|(?=<(?:CC)?STMTRS>)|\Z)", re.S | re.I
)
_TRANSACTION = re.compile(
    r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>)|\Z)", re.S | re.I
)


def _tag(block: str, name: str) -> str:
    """Value of ``<NAME>`` in SGML (no closing tag) or XML form, entities decoded."""
    match = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def parse_ofx(content: bytes) -> ParseResult[StatementLine]:
    text = decode(content)
    if "<OFX>" not in text.upper():
        raise ParseError("não é um arquivo OFX (tag <OFX> ausente)")
    statements = [match.group(2) for match in _STATEMENT.finditer(text)] or [text]

    result: ParseResult[StatementLine] = ParseResult()
    number = 0
    for statement in statements:
        account = _tag(statement, "ACCTID") or DEFAULT_ACCOUNT
        occurrences = _Occurrences()
        for match in _TRANSACTION.finditer(statement):
            number += 1
            block = match.group(1)
            try:
                posted = parse_date(_tag(block, "DTPOSTED")[:8])
                amount = parse_amount(_tag(block, "TRNAMT"))
            except ValueError as error:
                result.errors.append(f"lançamento {number}: {error}")
                continue
            name, memo = _tag(block, "NAME"), _tag(block, "MEMO")
            description = name if not memo or memo == name else f"{name} {memo}".strip()
            description = clean_description(description) or "(sem descrição)"
            fitid = _tag(block, "FITID")
            if not fitid:
                key = (posted, amount, description)
                fitid = "sem-fitid-" + short_hash(*key, occurrences.next(*key))
            elif (seen := occurrences.next("fitid", fitid)) > 1:
                # Some banks reuse a FITID inside one file; both lines are real payments.
                fitid = f"{fitid}#{seen}"
            result.rows.append(StatementLine(f"ofx:{account}:{fitid}", posted, amount, description))
    if not result.rows and not result.errors:
        raise ParseError("nenhum lançamento encontrado no OFX")
    return result


# -- CSV ----------------------------------------------------------------------------------

STATEMENT_COLUMNS = {
    "data": ("date", "data lancamento", "data do lancamento", "dt lancamento"),
    "descricao": ("descrição", "description", "historico", "histórico", "lancamento", "memo"),
    "valor": ("amount", "valor (r$)", "valor r$", "montante"),
    "id": ("documento", "identificador", "fitid", "nr documento"),
}


def parse_statement_csv(
    content: bytes, account: str = DEFAULT_ACCOUNT
) -> ParseResult[StatementLine]:
    """Columns ``data``, ``descricao`` and ``valor`` (negative = payment); ``id`` optional.

    A bank "document" number is not unique on its own (fees often share one), so it is
    combined with the date, the amount and an occurrence number.
    """
    result: ParseResult[StatementLine] = ParseResult()
    occurrences = _Occurrences()
    for row in read_csv(decode(content), STATEMENT_COLUMNS, {"data", "descricao", "valor"}):
        try:
            posted = parse_date(row.values["data"])
            amount = parse_amount(row.values["valor"])
        except ValueError as error:
            result.errors.append(f"linha {row.line}: {error}")
            continue
        description = clean_description(row.values["descricao"]) or "(sem descrição)"
        own_id = row.values.get("id", "")
        key = (account, posted, amount, own_id or description)
        external_id = "csv:" + short_hash(*key, occurrences.next(*key))
        result.rows.append(StatementLine(external_id, posted, amount, description))
    return result


def parse_statement(
    filename: str, content: bytes, account: str = DEFAULT_ACCOUNT
) -> ParseResult[StatementLine]:
    """Pick the reader from the file extension (``.ofx``/``.qfx`` or ``.csv``/``.txt``).

    ``account`` scopes CSV ids; OFX files carry their own account ids.
    """
    name = filename.lower()
    if name.endswith((".ofx", ".qfx")):
        return parse_ofx(content)
    if name.endswith((".csv", ".txt")):
        return parse_statement_csv(content, account)
    raise ParseError("formato não suportado para extrato; envie .ofx ou .csv")
