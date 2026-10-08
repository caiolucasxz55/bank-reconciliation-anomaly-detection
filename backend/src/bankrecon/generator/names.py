"""Invented supplier names and fake (but well-formed) CNPJs.

Names are combinations of made-up words: realism comes from the payment patterns,
never from real companies.
"""

from __future__ import annotations

import numpy as np

PREFIXES = (
    "Acme", "Norte", "Vale Verde", "Horizonte", "Atlas", "Prisma", "Aurora", "Delta",
    "Solaris", "Ipê", "Cedro", "Boreal", "Lumen", "Vértice", "Orion", "Pampa", "Serra Azul",
    "Maré", "Âncora", "Cobalto", "Brisa", "Farol", "Jacarandá", "Quartzo", "Zênite",
    "Alvorada", "Nimbus", "Cristal", "Pinhal", "Rio Claro",
)  # fmt: skip
SECTORS = (
    "Logística", "Transportes", "Serviços de Limpeza", "Tecnologia", "Embalagens",
    "Alimentos", "Energia", "Telecom", "Consultoria", "Manutenção Industrial", "Papelaria",
    "Segurança Patrimonial", "Química", "Metalúrgica", "Engenharia", "Marketing",
    "Contabilidade", "Locação de Equipamentos", "Software", "Têxtil",
)  # fmt: skip
SUFFIXES = ("Ltda", "S.A.", "Eireli", "ME")

_CNPJ_WEIGHTS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_2 = (6, *_CNPJ_WEIGHTS_1)


def generate_names(rng: np.random.Generator, count: int) -> list[str]:
    """Return ``count`` unique invented company names."""
    total = len(PREFIXES) * len(SECTORS)
    if count > total:
        raise ValueError(f"can generate at most {total} unique names, asked for {count}")
    picks = rng.choice(total, size=count, replace=False)
    names = []
    for pick in picks:
        prefix = PREFIXES[pick // len(SECTORS)]
        sector = SECTORS[pick % len(SECTORS)]
        suffix = SUFFIXES[int(rng.integers(len(SUFFIXES)))]
        names.append(f"{prefix} {sector} {suffix}")
    return names


def _check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def generate_cnpj(rng: np.random.Generator) -> str:
    """Random CNPJ with valid check digits, formatted ``00.000.000/0001-00``."""
    digits = [int(d) for d in rng.integers(0, 10, size=8)] + [0, 0, 0, 1]
    digits.append(_check_digit(digits, _CNPJ_WEIGHTS_1))
    digits.append(_check_digit(digits, _CNPJ_WEIGHTS_2))
    s = "".join(map(str, digits))
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


def is_valid_cnpj(cnpj: str) -> bool:
    digits = [int(c) for c in cnpj if c.isdigit()]
    if len(digits) != 14:
        return False
    return digits[12] == _check_digit(digits[:12], _CNPJ_WEIGHTS_1) and digits[13] == _check_digit(
        digits[:13], _CNPJ_WEIGHTS_2
    )
