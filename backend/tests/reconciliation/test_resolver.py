import pytest

from bankrecon.reconciliation.resolver import SupplierResolver, counterparty

SUPPLIERS = [
    ("S1", "Acme Logística e Transportes Ltda"),
    ("S2", "Lumen Segurança Patrimonial S.A."),
    ("S3", "Lumen Consultoria Eireli"),
    ("S4", "Vale Verde Papelaria ME"),
]


@pytest.fixture
def resolver():
    return SupplierResolver(SUPPLIERS)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("PIX ACME LOGISTICA", "ACME LOGISTICA"),
        ("PAG BOLETO LUMEN CONS", "LUMEN CONS"),
        ("TED Vale Verde", "VALE VERDE"),
        ("PIXACME", "PIXACME"),
        ("TRANSFERENCIA ACME", "TRANSFERENCIA ACME"),
    ],
)
def test_counterparty_strips_method_prefix(description, expected):
    assert counterparty(description) == expected


def test_exact_matches_name_prefix(resolver):
    assert resolver.exact("PIX ACME LOGISTICA E TRANSPORTES") == "S1"
    assert resolver.exact("PAG BOLETO LUMEN SEGURANCA PATRI") == "S2"


def test_exact_rejects_ambiguous_prefix(resolver):
    assert resolver.exact("PIX LUMEN") is None


def test_exact_rejects_too_short_fragment(resolver):
    assert resolver.exact("PIX ACME") is None


def test_exact_rejects_abbreviated_words(resolver):
    assert resolver.exact("PIX ACME LOGIST TRANS LT") is None


def test_candidates_returns_exact_match_alone(resolver):
    [candidate] = resolver.candidates("TED VALE VERDE PAPELARIA ME", min_score=0.6)
    assert (candidate.supplier_id, candidate.score) == ("S4", 1.0)


def test_candidates_fuzzy_ranks_the_right_supplier_first(resolver):
    candidates = resolver.candidates("PIX LUMEN CONSU EI", min_score=0.5)
    assert candidates[0].supplier_id == "S3"
    assert candidates[0].score < 1.0
    assert [c.score for c in candidates] == sorted((c.score for c in candidates), reverse=True)


def test_candidates_respects_min_score(resolver):
    assert resolver.candidates("PIX ZZZZZZZZ QQQQ", min_score=0.6) == []
