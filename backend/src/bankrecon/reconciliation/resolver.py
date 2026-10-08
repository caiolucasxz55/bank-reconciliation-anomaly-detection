"""Maps a bank statement description to the supplier it most likely refers to."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from bankrecon.text import normalize

# Payment-method prefixes banks put before the counterparty name, longest first.
METHOD_PREFIXES = ("PAG BOLETO", "PIX", "TED", "DOC")
# Too short a fragment (e.g. "PIX AC") would be a prefix of many names.
MIN_EXACT_PREFIX_LEN = 6


@dataclass(frozen=True)
class SupplierCandidate:
    supplier_id: str
    score: float  # similarity in [0, 1]; 1.0 for an exact prefix match


def counterparty(description: str) -> str:
    """Normalized description without the payment-method prefix."""
    text = normalize(description)
    for prefix in METHOD_PREFIXES:
        if text.startswith(prefix + " "):
            return text[len(prefix) + 1 :]
    return text


class SupplierResolver:
    """Exact lookup by name prefix, with a fuzzy fallback for abbreviated descriptions."""

    def __init__(self, suppliers: Iterable[tuple[str, str]]) -> None:
        """``suppliers`` is an iterable of ``(supplier_id, name)`` pairs."""
        self._names = {supplier_id: normalize(name) for supplier_id, name in suppliers}

    def exact(self, description: str) -> str | None:
        """Supplier whose normalized name starts with the description's counterparty.

        Returns ``None`` when no supplier or more than one supplier matches.
        """
        fragment = counterparty(description)
        if len(fragment) < MIN_EXACT_PREFIX_LEN:
            return None
        hits = [sid for sid, name in self._names.items() if name.startswith(fragment)]
        return hits[0] if len(hits) == 1 else None

    def candidates(
        self, description: str, min_score: float, limit: int = 3
    ) -> list[SupplierCandidate]:
        """Best suppliers for the description, highest score first.

        An exact prefix match is returned alone with score 1.0. Otherwise token-sort
        similarity is used: it tolerates abbreviated words and reordered tokens.
        """
        exact = self.exact(description)
        if exact is not None:
            return [SupplierCandidate(exact, 1.0)]
        results = process.extract(
            counterparty(description),
            self._names,
            scorer=fuzz.token_sort_ratio,
            limit=limit,
            score_cutoff=min_score * 100,
        )
        return [SupplierCandidate(sid, score / 100) for _, score, sid in results]
