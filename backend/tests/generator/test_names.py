import numpy as np
import pytest

from bankrecon.generator.names import (
    PREFIXES,
    SECTORS,
    generate_cnpj,
    generate_names,
    is_valid_cnpj,
)


def test_generate_names_are_unique():
    names = generate_names(np.random.default_rng(0), 100)
    assert len(set(names)) == 100


def test_generate_names_rejects_impossible_count():
    with pytest.raises(ValueError, match="at most"):
        generate_names(np.random.default_rng(0), len(PREFIXES) * len(SECTORS) + 1)


def test_generated_cnpjs_are_valid():
    rng = np.random.default_rng(0)
    for _ in range(50):
        assert is_valid_cnpj(generate_cnpj(rng))


def test_is_valid_cnpj_rejects_wrong_check_digit():
    assert is_valid_cnpj("11.222.333/0001-81")
    assert not is_valid_cnpj("11.222.333/0001-82")
    assert not is_valid_cnpj("123")
