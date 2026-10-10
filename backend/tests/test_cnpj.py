import pytest

from bankrecon.cnpj import format_cnpj, is_valid_cnpj, only_digits


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-81", "11222333000181", " 11.222.333/0001-81 "])
def test_valid_cnpj_in_any_format(cnpj):
    assert is_valid_cnpj(cnpj)


@pytest.mark.parametrize(
    "cnpj", ["11.222.333/0001-82", "123", "", "00000000000000", "11111111111111"]
)
def test_invalid_cnpj(cnpj):
    assert not is_valid_cnpj(cnpj)


def test_format_cnpj():
    assert format_cnpj("11222333000181") == "11.222.333/0001-81"
    assert format_cnpj("11.222.333/0001-81") == "11.222.333/0001-81"
    with pytest.raises(ValueError, match="14 dígitos"):
        format_cnpj("123")


def test_only_digits():
    assert only_digits("11.222.333/0001-81") == "11222333000181"


def test_only_ascii_digits_count():
    assert only_digits("1122233300018²") == "1122233300018"
    assert not is_valid_cnpj("1122233300018²")
