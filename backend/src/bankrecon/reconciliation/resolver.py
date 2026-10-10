"""Maps a bank statement description to the supplier it most likely refers to."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from bankrecon.text import normalize

# Words banks put before the counterparty name ("PIX ENVIADO", "PAGAMENTO DE BOLETO",
# "TRANSF ENVIADA", "DEB AUT", "SISPAG"...). Only a leading run of them is removed.
LEADING_NOISE = frozenset(
    {
        "PIX", "TED", "DOC", "PAG", "PAGTO", "PGTO", "PAGAMENTO", "PAGAMENTOS", "BOLETO",
        "BOLETOS", "TIT", "TITULO", "TITULOS", "ENVIADO", "ENVIADA", "ENVIO", "EMITIDO",
        "EMITIDA", "TRANSF", "TRANSFERENCIA", "DEB", "DEBITO", "AUT", "AUTOMATICO",
        "SISPAG", "QR", "CODE", "INTERNET", "IB", "DE", "PARA", "A", "-",
    }
)  # fmt: skip
# Too short a fragment (e.g. "PIX AC") would be a prefix of many names.
MIN_EXACT_PREFIX_LEN = 6


@dataclass(frozen=True)
class SupplierCandidate:
    supplier_id: str
    score: float  # similarity in [0, 1]; 1.0 for an exact prefix match


def counterparty_variants(description: str) -> list[str]:
    """The normalized description with 0, 1, 2... leading noise words removed.

    Least stripped first: a name may itself start with a "noise" word (DE MARCHI, A
    PREFERIDA), so the exact lookup tries every variant before giving up.
    """
    words = normalize(description).split()
    variants = [" ".join(words)]
    start = 0
    # Keep at least one word: a description made only of noise is left as it is.
    while start < len(words) - 1 and words[start] in LEADING_NOISE:
        start += 1
        variants.append(" ".join(words[start:]))
    return variants


def counterparty(description: str) -> str:
    """Normalized description without the payment-method words before the name."""
    return counterparty_variants(description)[-1]


class SupplierResolver:
    """Exact lookup by name prefix, with a fuzzy fallback for abbreviated descriptions."""

    def __init__(self, suppliers: Iterable[tuple[str, str]]) -> None:
        """``suppliers`` is an iterable of ``(supplier_id, name)`` pairs."""
        self._names = {supplier_id: normalize(name) for supplier_id, name in suppliers}

    def exact(self, description: str) -> str | None:
        """Supplier whose normalized name starts with the description's counterparty.

        Returns ``None`` when no supplier or more than one supplier matches.
        """
        for fragment in counterparty_variants(description):
            if len(fragment) < MIN_EXACT_PREFIX_LEN:
                continue
            hits = [sid for sid, name in self._names.items() if name.startswith(fragment)]
            if len(hits) == 1:
                return hits[0]
            if hits:
                return None  # ambiguous: a shorter fragment would only be more ambiguous
        return None

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
