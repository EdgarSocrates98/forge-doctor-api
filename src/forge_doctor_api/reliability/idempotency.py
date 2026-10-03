"""Idempotency evidence aggregation (§42).

A verdict requires at least one source that actually asserts
idempotent or non-idempotent semantics. HTTP method alone NEVER
decides - POST is not assumed non-idempotent, PUT not assumed
idempotent.
"""

from __future__ import annotations

from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.reliability.model import (
    IdempotencyEvidence,
    IdempotencySource,
    IdempotencyVerdict,
)


def aggregate_idempotency(
    subject: str, sources: tuple[IdempotencySource, ...]
) -> IdempotencyEvidence:
    """§42 aggregate -> verdict or UNKNOWN with the gap listed."""
    asserted = [s for s in sources if s.supports is not None]
    unknowns: list[UnknownFact] = []
    if not asserted:
        verdict = IdempotencyVerdict.UNKNOWN
        unknowns.append(
            UnknownFact(
                subject=subject,
                missing="evidence asserting idempotent semantics "
                "(idempotency key, contract metadata, handler semantics, "
                "db uniqueness)",
                resolution="declare x-idempotent, an idempotency-key "
                "header, or provide handler semantics",
            )
        )
    elif any(s.supports is False for s in asserted):
        verdict = IdempotencyVerdict.NON_IDEMPOTENT
    else:
        verdict = IdempotencyVerdict.IDEMPOTENT
    return IdempotencyEvidence(
        subject=subject,
        sources=sources,
        verdict=verdict,
        unknowns=tuple(unknowns),
    )
