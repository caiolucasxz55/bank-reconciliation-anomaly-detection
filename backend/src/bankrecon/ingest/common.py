"""Parsing helpers shared by the statement and invoice readers."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Generic, TypeVar

from bankrecon.text import normalize

T = TypeVar("T")

# Imported files are untrusted: cap their size before parsing.
MAX_FILE_BYTES = 10 * 1024 * 1024
DESCRIPTION_MAX_LEN = 255


class ParseError(ValueError):
    """The file as a whole cannot be read (wrong format, missing columns...)."""


@dataclass
class ParseResult(Generic[T]):
    """Rows read from one file, plus what was left out and why."""

    rows: list[T] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def decode(content: bytes) -> str:
    """Text of an uploaded file: UTF-8 (with or without BOM), else Windows-1252."""
    if len(content) > MAX_FILE_BYTES:
        raise ParseError(f"arquivo maior que {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


_NUMBER_JUNK = re.compile(r"[R$\s ]")


_THOUSANDS_ONLY = re.compile(r"^-?\d{1,3}([.,]\d{3})+$")


def parse_amount(text: str) -> Decimal:
    """Brazilian or international amounts: ``1.234,56``, ``-1234.56``, ``R$ (10,00)``.

    A lone separator followed by exactly three digits (``1.500``, ``2,000``) is read as a
    thousands separator, as money is written with two decimals or none.
    """
    raw = _NUMBER_JUNK.sub("", text or "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    if raw.endswith("-"):  # some banks print "123,45-"
        negative, raw = True, raw[:-1]
    if _THOUSANDS_ONLY.match(raw):
        raw = raw.replace(".", "").replace(",", "")
    elif "," in raw and "." in raw:
        # The last separator is the decimal one.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError(f"valor inválido: {text!r}") from error
    if not value.is_finite():
        raise ValueError(f"valor inválido: {text!r}")
    return -value if negative else value


_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y%m%d", "%d.%m.%Y")


def parse_date(text: str) -> date:
    """Dates as banks and ERPs export them; a time part (``T10:15``, `` 10:15``) is ignored."""
    raw = (text or "").strip()
    # "2025-03-10T10:00:00-03:00" or "07/04/2025 10:15" -> keep the date part.
    date_part = raw.split("T", 1)[0] if len(raw) > 10 and raw[4:5] == "-" else raw
    date_part = date_part.split(" ", 1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {text!r}")


def clean_description(text: str) -> str:
    return " ".join((text or "").split())[:DESCRIPTION_MAX_LEN]


def short_hash(*parts: object) -> str:
    joined = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]


# -- CSV ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CsvRow:
    line: int
    values: dict[str, str]


def read_csv(
    text: str, aliases: dict[str, tuple[str, ...]], required: set[str]
) -> Iterator[CsvRow]:
    """Rows keyed by canonical column name.

    ``aliases`` maps each canonical name to accepted header spellings (compared without
    accents or case). The delimiter (``;``, ``,`` or tab) is detected from the header.
    """
    lines = text.splitlines()
    header_line = next((line for line in lines if line.strip()), "")
    delimiter = max(";,\t", key=header_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    header: list[str] | None = None
    columns: dict[str, int] = {}
    for line_number, row in enumerate(reader, start=1):
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = [normalize(cell).lower() for cell in row]
            for canonical, spellings in aliases.items():
                for spelling in (canonical, *spellings):
                    if normalize(spelling).lower() in header:
                        columns[canonical] = header.index(normalize(spelling).lower())
                        break
            missing = sorted(required - columns.keys())
            if missing:
                raise ParseError(f"colunas obrigatórias ausentes: {', '.join(missing)}")
            continue
        values = {
            name: row[index].strip() if index < len(row) else "" for name, index in columns.items()
        }
        yield CsvRow(line_number, values)
    if header is None:
        raise ParseError("arquivo vazio")
