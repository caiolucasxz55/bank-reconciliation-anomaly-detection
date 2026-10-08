import pytest

from bankrecon.text import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ipê Logística  S.A.", "IPE LOGISTICA S A"),
        ("  zênite-química ltda ", "ZENITE QUIMICA LTDA"),
        ("ÂNCORA & CIA", "ANCORA CIA"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected
