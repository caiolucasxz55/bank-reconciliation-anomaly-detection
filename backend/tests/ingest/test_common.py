from datetime import date
from decimal import Decimal

import pytest

from bankrecon.ingest.common import (
    MAX_FILE_BYTES,
    ParseError,
    decode,
    parse_amount,
    parse_date,
    read_csv,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.234,56", "1234.56"),
        ("-1.234,56", "-1234.56"),
        ("1,234.56", "1234.56"),
        ("-1500.00", "-1500.00"),
        ("12,90", "12.90"),
        ("R$ 1.500,00", "1500.00"),
        ("(10,00)", "-10.00"),
        ("123,45-", "-123.45"),
        ("1.234.567", "1234567"),
        ("0.5", "0.5"),
        (" 1 000,00", "1000.00"),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "abc", "1,2,3x", "NaN", "Infinity"])
def test_parse_amount_rejects_garbage(text):
    with pytest.raises(ValueError, match="valor inválido"):
        parse_amount(text)


@pytest.mark.parametrize(
    "text",
    ["07/04/2025", "2025-04-07", "07-04-2025", "07/04/25", "20250407", "07.04.2025",
     "2025-04-07T10:15:00-03:00"],
)  # fmt: skip
def test_parse_date(text):
    assert parse_date(text) == date(2025, 4, 7)


@pytest.mark.parametrize("text", ["", "31/02/2025", "ontem"])
def test_parse_date_rejects_garbage(text):
    with pytest.raises(ValueError, match="data inválida"):
        parse_date(text)


def test_decode_handles_bom_and_windows_1252():
    assert decode("﻿Logística".encode()) == "Logística"
    assert decode("Logística".encode("cp1252")) == "Logística"


def test_decode_rejects_huge_files():
    with pytest.raises(ParseError, match="MB"):
        decode(b"x" * (MAX_FILE_BYTES + 1))


ALIASES = {"data": ("date",), "valor": ("amount", "valor (r$)")}


@pytest.mark.parametrize("delimiter", [";", ",", "\t"])
def test_read_csv_detects_delimiter_and_header_spelling(delimiter):
    text = f"Date{delimiter}Valor (R$)\n01/02/2025{delimiter}10\n\n02/02/2025{delimiter}20\n"
    rows = list(read_csv(text, ALIASES, {"data", "valor"}))
    assert [r.values for r in rows] == [
        {"data": "01/02/2025", "valor": "10"},
        {"data": "02/02/2025", "valor": "20"},
    ]
    assert [r.line for r in rows] == [2, 4]


def test_read_csv_reports_missing_columns():
    with pytest.raises(ParseError, match="colunas obrigatórias ausentes: valor"):
        list(read_csv("data;outra\n01/01/2025;x\n", ALIASES, {"data", "valor"}))


def test_read_csv_rejects_empty_file():
    with pytest.raises(ParseError, match="vazio"):
        list(read_csv("\n\n", ALIASES, {"data"}))
