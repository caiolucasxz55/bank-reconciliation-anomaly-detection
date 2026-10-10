"""CNPJ (Brazilian company tax id) check digits, validation and formatting."""

from __future__ import annotations

CNPJ_LENGTH = 14
_WEIGHTS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_WEIGHTS_2 = (6, *_WEIGHTS_1)


def check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def with_check_digits(first_twelve: list[int]) -> str:
    """The 14 digits of a CNPJ whose first 12 digits are ``first_twelve``."""
    digits = list(first_twelve)
    digits.append(check_digit(digits, _WEIGHTS_1))
    digits.append(check_digit(digits, _WEIGHTS_2))
    return "".join(map(str, digits))


_ASCII_DIGITS = frozenset("0123456789")


def only_digits(value: str) -> str:
    """ASCII digits of ``value`` (``str.isdigit`` would also accept "²" and others)."""
    return "".join(c for c in value if c in _ASCII_DIGITS)


def is_valid_cnpj(cnpj: str) -> bool:
    digits = only_digits(cnpj)
    if len(digits) != CNPJ_LENGTH or len(set(digits)) == 1:
        return False
    return with_check_digits([int(d) for d in digits[:12]]) == digits


def format_cnpj(cnpj: str) -> str:
    """``11222333000181`` (or already formatted) -> ``11.222.333/0001-81``."""
    s = only_digits(cnpj)
    if len(s) != CNPJ_LENGTH:
        raise ValueError(f"CNPJ deve ter 14 dígitos: {cnpj!r}")
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
