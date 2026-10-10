from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankrecon.ingest import ParseError, parse_statement
from bankrecon.ingest.statement import parse_ofx, parse_statement_csv

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_ofx_v1_sgml_windows_1252():
    result = parse_ofx(_read("extrato_v1.ofx"))
    assert result.errors == []
    assert [line.amount for line in result.rows] == [
        Decimal("-1500.00"),
        Decimal("5000.00"),
        Decimal("-845.90"),
        Decimal("-12.90"),  # comma decimal in TRNAMT
    ]
    first = result.rows[0]
    assert first.date == date(2025, 4, 7)
    assert first.description == "PIX ENVIADO ACME LOGÍSTICA LTDA"
    assert first.external_id == "ofx:12345-6:202504070001"


def test_ofx_v2_xml_combines_name_and_memo():
    result = parse_ofx(_read("extrato_v2.ofx"))
    assert [line.description for line in result.rows] == [
        "PIX ENVIADO ACME LOGISTICA E TRANSPORTES",
        "PAG BOLETO ENERGIA",
    ]
    assert result.rows[0].external_id == "ofx:98765-4:A1B2C3"
    assert result.rows[0].date == date(2025, 5, 5)


def test_ofx_ids_are_stable_across_reads():
    assert parse_ofx(_read("extrato_v1.ofx")).rows == parse_ofx(_read("extrato_v1.ofx")).rows


def test_ofx_without_fitid_is_stable_across_periods():
    tx = b"<STMTTRN><DTPOSTED>20250410<TRNAMT>-100.00<MEMO>PIX ACME</STMTTRN>"
    other = b"<STMTTRN><DTPOSTED>20250402<TRNAMT>-5.00<MEMO>PIX NORTE</STMTTRN>"
    [alone] = parse_ofx(b"<OFX>" + tx + b"</OFX>").rows
    later = parse_ofx(b"<OFX>" + other + tx + b"</OFX>").rows[1]
    assert alone.external_id == later.external_id


def test_ofx_with_two_accounts_keeps_each_account():
    content = (
        b"<OFX><STMTRS><ACCTID>111<STMTTRN><DTPOSTED>20250101<TRNAMT>-1.00<FITID>9"
        b"</STMTTRN></STMTRS><STMTRS><ACCTID>222<STMTTRN><DTPOSTED>20250101"
        b"<TRNAMT>-1.00<FITID>9</STMTTRN></STMTRS></OFX>"
    )
    ids = [line.external_id for line in parse_ofx(content).rows]
    assert ids == ["ofx:111:9", "ofx:222:9"]


def test_ofx_xml_entities_are_decoded():
    content = (
        b"<OFX><STMTTRN><DTPOSTED>20250101</DTPOSTED><TRNAMT>-1.00</TRNAMT>"
        b"<MEMO>SILVA &amp; FILHOS</MEMO></STMTTRN></OFX>"
    )
    [line] = parse_ofx(content).rows
    assert line.description == "SILVA & FILHOS"


def test_ofx_without_fitid_gets_a_content_id():
    content = b"<OFX><STMTTRN><DTPOSTED>20250101<TRNAMT>-1.00<MEMO>X</STMTTRN></OFX>"
    [line] = parse_ofx(content).rows
    assert line.external_id.startswith("ofx:conta:sem-fitid-")


def test_ofx_bad_transaction_is_reported_and_skipped():
    content = (
        b"<OFX><STMTTRN><DTPOSTED>20250101<TRNAMT>abc<FITID>1</STMTTRN>"
        b"<STMTTRN><DTPOSTED>20250102<TRNAMT>-2.00<FITID>2<MEMO>OK</STMTTRN></OFX>"
    )
    result = parse_ofx(content)
    assert len(result.rows) == 1
    assert result.errors == ["lançamento 1: valor inválido: 'abc'"]


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"Data;Valor\n", "não é um arquivo OFX"), (b"<OFX></OFX>", "nenhum lançamento")],
)
def test_invalid_ofx(content, message):
    with pytest.raises(ParseError, match=message):
        parse_ofx(content)


def test_csv_statement():
    result = parse_statement_csv(_read("extrato.csv"))
    assert result.errors == ["linha 7: valor inválido: 'abc'"]
    assert [line.amount for line in result.rows] == [
        Decimal("-1500.00"),
        Decimal("5000.00"),
        Decimal("-845.90"),
        Decimal("-230.00"),
        Decimal("-230.00"),
    ]
    # Two identical payments on the same day stay two distinct lines.
    assert result.rows[3].external_id != result.rows[4].external_id


def test_csv_ids_are_stable_across_reads():
    first = [line.external_id for line in parse_statement_csv(_read("extrato.csv")).rows]
    again = [line.external_id for line in parse_statement_csv(_read("extrato.csv")).rows]
    assert first == again


def test_repeated_document_numbers_stay_distinct():
    content = (
        b"data;descricao;valor;documento\n"
        b"02/01/2025;TARIFA;-12,90;0\n"
        b"02/01/2025;PIX;-50,00;0\n"
        b"03/01/2025;TARIFA;-12,90;0\n"
    )
    ids = [line.external_id for line in parse_statement_csv(content).rows]
    assert len(set(ids)) == 3


def test_csv_ids_are_scoped_by_account():
    content = b"data;descricao;valor\n02/01/2025;TARIFA PACOTE;-12,90\n"
    [checking] = parse_statement_csv(content, account="corrente").rows
    [savings] = parse_statement_csv(content, account="poupanca").rows
    assert checking.external_id != savings.external_id


def test_csv_ids_do_not_depend_on_the_statement_period():
    april_first_half = b"data;descricao;valor\n10/04/2025;PIX ACME;-100,00\n"
    whole_april = b"data;descricao;valor\n02/04/2025;PIX NORTE;-5,00\n10/04/2025;PIX ACME;-100,00\n"
    [first] = parse_statement_csv(april_first_half).rows
    assert first.external_id == parse_statement_csv(whole_april).rows[1].external_id


@pytest.mark.parametrize(
    ("filename", "fixture"),
    [("extrato.OFX", "extrato_v1.ofx"), ("banco.qfx", "extrato_v2.ofx"), ("x.csv", "extrato.csv")],
)
def test_parse_statement_dispatches_by_extension(filename, fixture):
    assert parse_statement(filename, _read(fixture)).rows


def test_parse_statement_rejects_unknown_formats():
    with pytest.raises(ParseError, match=r"envie .ofx ou .csv"):
        parse_statement("extrato.pdf", b"%PDF")
