"""Text normalization shared by the generator and the reconciliation engine."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Uppercase, strip accents and punctuation, collapse whitespace.

    >>> normalize("Ipê Logística  S.A.")
    'IPE LOGISTICA S A'
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = _NON_ALNUM.sub(" ", ascii_text.upper())
    return _SPACES.sub(" ", cleaned).strip()
