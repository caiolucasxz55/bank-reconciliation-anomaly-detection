from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankrecon.ingest import ParseError, parse_invoice_file, parse_nfe
from bankrecon.ingest.invoices import parse_invoices_csv

FIXTURES = Path(__file__).parent / "fixtures"
KEY = "35250345997418000153550010000012341123456789"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_nfe_with_installments_becomes_one_payable_per_installment():
    first, second = parse_nfe(_read("nfe_parcelada.xml"))
    assert first.invoice_id == f"{KEY}-001"
    assert first.number == "1234/001"
    assert first.supplier_tax_id == "45.997.418/0001-53"
    assert first.supplier_name == "Acme Logística e Transportes Ltda"
    assert first.issue_date == date(2025, 3, 5)
    assert first.due_date == date(2025, 4, 5)
    assert first.amount == Decimal("1500.00")
    assert second.due_date == date(2025, 5, 5)


def test_nfe_without_installments_is_a_single_payable():
    [invoice] = parse_nfe(_read("nfe_a_vista.xml"))
    assert invoice.invoice_id == "35250427865757000102550010000000881987654321"
    assert invoice.number == "88"
    assert invoice.due_date is None
    assert invoice.amount == Decimal("845.90")


def test_cancelled_nfe_is_rejected():
    with pytest.raises(ParseError, match=r"não autorizada.*101.*Cancelamento"):
        parse_nfe(_read("nfe_cancelada.xml"))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"not xml", "XML inválido"),
        (b"<root/>", "não é uma NF-e"),
        (
            b'<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe Id="NFe123"/></NFe>',
            "chave de acesso",
        ),
    ],
)
def test_invalid_nfe(content, message):
    with pytest.raises(ParseError, match=message):
        parse_nfe(content)


def test_nfe_from_a_person_is_rejected():
    content = _read("nfe_a_vista.xml").replace(
        b"<CNPJ>27865757000102</CNPJ>", b"<CPF>12345678909</CPF>"
    )
    with pytest.raises(ParseError, match="sem CNPJ válido"):
        parse_nfe(content)


def test_xml_entity_attacks_are_blocked():
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;">]><NFe>&lol2;</NFe>'
    )
    with pytest.raises(ParseError, match="XML inválido"):
        parse_nfe(bomb)


def test_invoices_csv():
    result = parse_invoices_csv(_read("notas.csv"))
    assert result.errors == ["linha 5: CNPJ inválido: '11.111.111/1111-11'"]
    first, second, third = result.rows
    assert first.invoice_id == "45997418000153-1234-1"
    assert first.number == "1234/1"
    assert first.due_date == date(2025, 4, 5)
    assert first.amount == Decimal("1500.00")
    assert second.invoice_id == "45997418000153-1234-2"
    assert third.invoice_id == "27865757000102-88"
    assert third.supplier_tax_id == "27.865.757/0001-02"
    assert third.due_date is None


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("1;45997418000153;X;01/01/2025;;-5,00", "valor deve ser positivo"),
        (";45997418000153;X;01/01/2025;;5,00", "número da nota vazio"),
        ("1;45997418000153;X;ontem;;5,00", "data inválida"),
    ],
)
def test_invoices_csv_row_errors(line, message):
    content = f"numero;cnpj;fornecedor;emissao;vencimento;valor\n{line}\n".encode()
    result = parse_invoices_csv(content)
    assert result.rows == []
    assert message in result.errors[0]


def test_parse_invoice_file_dispatches_by_extension():
    assert len(parse_invoice_file("NF.XML", _read("nfe_parcelada.xml")).rows) == 2
    assert len(parse_invoice_file("notas.csv", _read("notas.csv")).rows) == 3
    with pytest.raises(ParseError, match=r"envie \.xml"):
        parse_invoice_file("nota.pdf", b"%PDF")
