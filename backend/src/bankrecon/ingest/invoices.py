"""Invoice readers: NF-e XML (one payable per installment) and CSV."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError as XmlParseError
from defusedxml.ElementTree import fromstring

from bankrecon.cnpj import format_cnpj, is_valid_cnpj, only_digits
from bankrecon.ingest.common import (
    MAX_FILE_BYTES,
    ParseError,
    ParseResult,
    decode,
    parse_amount,
    parse_date,
    read_csv,
)

NFE_NAMESPACE = "{http://www.portalfiscal.inf.br/nfe}"
# Authorization status codes of an NF-e (100 = authorized, 150 = authorized late).
AUTHORIZED = {"100", "150"}
ACCESS_KEY_LENGTH = 44


# Series most invoices use; it is left out of ids so spreadsheets without a series column
# still match the NF-e XML of the same invoice.
DEFAULT_SERIES = {"", "0", "1"}
_NUMERIC = re.compile(r"[\d.\s/-]+")


def canonical_number(value: str) -> str:
    """'001' -> '1' and '000.001.234' -> '1234', so number formats from XML, ERPs and
    spreadsheets agree; anything else (letters) is kept as typed."""
    value = value.strip()
    if _NUMERIC.fullmatch(value) and (digits := only_digits(value)):
        return digits.lstrip("0") or "0"
    return value


def payable_id(cnpj: str, number: str, installment: str = "", series: str = "") -> str:
    """Id of a payable, the same whatever the file format it came from.

    Supplier CNPJ + series (only when not the default) + invoice number + installment:
    importing the same invoice from an NF-e XML and from a spreadsheet is recognized as a
    duplicate, while invoices with the same number in different series stay distinct
    (NF-e numbering restarts per series).
    """
    parts = [only_digits(cnpj)]
    if (series := canonical_number(series)) not in DEFAULT_SERIES:
        parts.append(f"s{series}")
    parts.append(canonical_number(number))
    if installment.strip():
        parts.append(canonical_number(installment))
    return "-".join(parts)


@dataclass(frozen=True)
class ParsedInvoice:
    """A payable: a whole invoice or one of its installments."""

    # See payable_id: CNPJ + invoice number (+ installment).
    invoice_id: str
    number: str
    supplier_tax_id: str  # formatted CNPJ
    supplier_name: str
    issue_date: date
    # When payment is expected (installment due date); None if the file does not say.
    due_date: date | None
    amount: Decimal


# -- NF-e XML -------------------------------------------------------------------------------


def _find(element: Element, path: str) -> Element | None:
    return element.find("/".join(NFE_NAMESPACE + part for part in path.split("/")))


def _text(element: Element, path: str) -> str:
    found = _find(element, path)
    return (found.text or "").strip() if found is not None else ""


def parse_nfe(content: bytes) -> list[ParsedInvoice]:
    """Payables of one NF-e file (``nfeProc`` or bare ``NFe``).

    Each ``<dup>`` installment becomes a payable due on its ``dVenc``; an invoice without
    installments is a single payable of ``vNF``.
    """
    if len(content) > MAX_FILE_BYTES:
        raise ParseError(f"arquivo maior que {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        # Raw bytes: the parser honours the encoding declared in the XML prolog.
        root = fromstring(content)
    except (XmlParseError, DefusedXmlException) as error:
        raise ParseError(f"XML inválido: {error}") from error

    info = root if root.tag == NFE_NAMESPACE + "infNFe" else None
    if info is None:
        info = next(root.iter(NFE_NAMESPACE + "infNFe"), None)
    if info is None:
        raise ParseError("não é uma NF-e (elemento infNFe ausente)")

    status = _text(root, "protNFe/infProt/cStat")
    if status and status not in AUTHORIZED:
        reason = _text(root, "protNFe/infProt/xMotivo") or "sem motivo informado"
        raise ParseError(f"NF-e não autorizada (cStat {status}: {reason})")

    access_key = only_digits(info.get("Id", ""))
    if len(access_key) != ACCESS_KEY_LENGTH:
        raise ParseError("chave de acesso ausente ou inválida (atributo Id de infNFe)")
    cnpj = _text(info, "emit/CNPJ")
    if not is_valid_cnpj(cnpj):
        raise ParseError("emitente sem CNPJ válido (notas de pessoa física não são aceitas)")
    number = _text(info, "ide/nNF")
    series = _text(info, "ide/serie")
    try:
        issued = parse_date(_text(info, "ide/dhEmi") or _text(info, "ide/dEmi"))
        installments = [
            (
                _text(dup, "nDup") or str(index),
                parse_date(_text(dup, "dVenc")),
                parse_amount(_text(dup, "vDup")),
            )
            for index, dup in enumerate(info.iter(NFE_NAMESPACE + "dup"), start=1)
        ]
        total = parse_amount(_text(info, "total/ICMSTot/vNF"))
    except ValueError as error:
        raise ParseError(f"NF-e {number or access_key}: {error}") from error

    common = {
        "supplier_tax_id": format_cnpj(cnpj),
        "supplier_name": _text(info, "emit/xNome") or _text(info, "emit/xFant"),
        "issue_date": issued,
    }
    if not installments:
        return [
            ParsedInvoice(
                invoice_id=payable_id(cnpj, number, series=series),
                number=number,
                due_date=None,
                amount=total,
                **common,
            )
        ]
    return [
        ParsedInvoice(
            invoice_id=payable_id(cnpj, number, n_dup, series),
            number=f"{number}/{n_dup}",
            due_date=due,
            amount=amount,
            **common,
        )
        for n_dup, due, amount in installments
    ]


# -- CSV ----------------------------------------------------------------------------------

INVOICE_COLUMNS = {
    "numero": ("número", "nf", "numero nf", "nota", "documento"),
    "cnpj": ("cnpj fornecedor", "cnpj emitente"),
    "fornecedor": ("razao social", "razão social", "nome", "emitente"),
    "emissao": ("data emissao", "data de emissao", "data_emissao", "emitida em"),
    "vencimento": ("data vencimento", "data de vencimento", "data_vencimento", "vence em"),
    "valor": ("valor total", "valor da nota", "amount"),
    "parcela": ("nº parcela", "numero parcela"),
    "serie": ("série", "serie nf"),
}


def parse_invoices_csv(content: bytes) -> ParseResult[ParsedInvoice]:
    """Columns ``numero``, ``cnpj``, ``emissao`` and ``valor``; ``fornecedor``,
    ``vencimento``, ``parcela`` and ``serie`` optional."""
    result: ParseResult[ParsedInvoice] = ParseResult()
    required = {"numero", "cnpj", "emissao", "valor"}
    for row in read_csv(decode(content), INVOICE_COLUMNS, required):
        v = row.values
        try:
            if not is_valid_cnpj(v["cnpj"]):
                raise ValueError(f"CNPJ inválido: {v['cnpj']!r}")
            if not v["numero"]:
                raise ValueError("número da nota vazio")
            amount = parse_amount(v["valor"])
            if amount <= 0:
                raise ValueError(f"valor deve ser positivo: {v['valor']!r}")
            issued = parse_date(v["emissao"])
            due = parse_date(v["vencimento"]) if v.get("vencimento") else None
        except ValueError as error:
            result.errors.append(f"linha {row.line}: {error}")
            continue
        installment = v.get("parcela", "")
        invoice_id = payable_id(v["cnpj"], v["numero"], installment, v.get("serie", ""))
        number = f"{v['numero']}/{installment}" if installment else v["numero"]
        result.rows.append(
            ParsedInvoice(
                invoice_id=invoice_id,
                number=number,
                supplier_tax_id=format_cnpj(v["cnpj"]),
                supplier_name=v.get("fornecedor", ""),
                issue_date=issued,
                due_date=due,
                amount=amount,
            )
        )
    return result


def parse_invoice_file(filename: str, content: bytes) -> ParseResult[ParsedInvoice]:
    """Pick the reader from the extension.

    An unreadable NF-e (cancelled, invalid...) is reported in ``errors`` so a batch of
    XML files keeps going; an unsupported extension or a CSV without the required
    columns raises ``ParseError``.
    """
    name = filename.lower()
    if name.endswith(".xml"):
        try:
            return ParseResult(rows=parse_nfe(content))
        except ParseError as error:
            return ParseResult(errors=[f"{filename}: {error}"])
    if name.endswith((".csv", ".txt")):
        return parse_invoices_csv(content)
    raise ParseError("formato não suportado para notas; envie .xml (NF-e) ou .csv")
