"""Conventions shared by every stage's tabular files."""

from collections.abc import Iterable

# Separator for list-valued cells (e.g. the invoice ids a transaction pays) in CSV files.
LIST_SEPARATOR = ";"


def split_list(value: str) -> list[str]:
    return value.split(LIST_SEPARATOR) if value else []


def join_list(values: Iterable[str]) -> str:
    return LIST_SEPARATOR.join(values)
