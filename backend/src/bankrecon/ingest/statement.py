"""Bank statement readers: OFX (SGML 1.x and XML 2.x) and CSV."""

from __future__ import annotations

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


@dataclass(frozen=True)
class StatementLine:
    # Stable across reimports of the same statement, so duplicates are recognized.
    external_id: str
    date: date
    # Signed as in the statement: negative = money out (a payment).
    amount: Decimal
    description: str


# -- OFX ----------------------------------------------------------------------------------

_TRANSACTION = re.compile(
    r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", re.S | re.I
)
_ACCOUNT = re.compile(r"<ACCTID>([^<\r\n]+)", re.I)


def _tag(block: str, name: str) -> str:
    """Value of ``<NAME>`` in SGML (no closing tag) or XML form."""
    match = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return match.group(1).strip() if match else ""


def parse_ofx(content: bytes) -> ParseResult[StatementLine]:
    text = decode(content)
    if "<OFX>" not in text.upper():
        raise ParseError("não é um arquivo OFX (tag <OFX> ausente)")
    account_match = _ACCOUNT.search(text)
    account = account_match.group(1).strip() if account_match else "conta"

    result: ParseResult[StatementLine] = ParseResult()
    for number, match in enumerate(_TRANSACTION.finditer(text), start=1):
        block = match.group(1)
        fitid = _tag(block, "FITID")
        try:
            posted = parse_date(_tag(block, "DTPOSTED")[:8])
            amount = parse_amount(_tag(block, "TRNAMT"))
        except ValueError as error:
            result.errors.append(f"lançamento {number}: {error}")
            continue
        name, memo = _tag(block, "NAME"), _tag(block, "MEMO")
        description = name if not memo or memo == name else f"{name} {memo}".strip()
        if not fitid:
            # Without FITID, identify the line by its content (stable on reimport).
            fitid = "sem-fitid-" + short_hash(posted, amount, description, number)
        result.rows.append(
            StatementLine(
                external_id=f"ofx:{account}:{fitid}",
                date=posted,
                amount=amount,
                description=clean_description(description) or "(sem descrição)",
            )
        )
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


def parse_statement_csv(content: bytes) -> ParseResult[StatementLine]:
    """Columns ``data``, ``descricao`` and ``valor`` (negative = payment); ``id`` optional."""
    result: ParseResult[StatementLine] = ParseResult()
    seen: Counter[tuple] = Counter()
    for row in read_csv(decode(content), STATEMENT_COLUMNS, {"data", "descricao", "valor"}):
        try:
            posted = parse_date(row.values["data"])
            amount = parse_amount(row.values["valor"])
        except ValueError as error:
            result.errors.append(f"linha {row.line}: {error}")
            continue
        description = clean_description(row.values["descricao"]) or "(sem descrição)"
        if own_id := row.values.get("id"):
            external_id = f"csv:{own_id}"
        else:
            # Identical lines (two equal payments on one day) stay distinct by occurrence.
            key = (posted, amount, description)
            seen[key] += 1
            external_id = "csv:" + short_hash(*key, seen[key])
        result.rows.append(StatementLine(external_id, posted, amount, description))
    return result


def parse_statement(filename: str, content: bytes) -> ParseResult[StatementLine]:
    """Pick the reader from the file extension (``.ofx``/``.qfx`` or ``.csv``/``.txt``)."""
    name = filename.lower()
    if name.endswith((".ofx", ".qfx")):
        return parse_ofx(content)
    if name.endswith((".csv", ".txt")):
        return parse_statement_csv(content)
    raise ParseError("formato não suportado para extrato; envie .ofx ou .csv")
