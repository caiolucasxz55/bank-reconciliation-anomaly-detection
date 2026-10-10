"""Invented supplier names and fake (but well-formed) CNPJs.

Names are combinations of made-up words: realism comes from the payment patterns,
never from real companies.
"""

from __future__ import annotations

import numpy as np

from bankrecon.cnpj import format_cnpj, with_check_digits

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


def generate_cnpj(rng: np.random.Generator) -> str:
    """Random CNPJ with valid check digits, formatted ``00.000.000/0001-00``."""
    digits = [int(d) for d in rng.integers(0, 10, size=8)] + [0, 0, 0, 1]
    return format_cnpj(with_check_digits(digits))
