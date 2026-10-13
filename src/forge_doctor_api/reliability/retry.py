"""Retry amplification math (§40-41).

Amplification multiplies only hops with an *explicit* declared
`max_attempts`. Hops without a declared policy are listed under
`missing` and the total stays `None` -> UNKNOWN (§41 forbids assumed
defaults).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Confidence, Model, UnknownFact
from forge_doctor_api.reliability.model import RetryPolicy


@dataclass(frozen=True, kw_only=True)
class RetryAmplification(Model):
    """Product of stacked explicit retry policies along a path."""

    hops: tuple[str, ...]
    policies: tuple[RetryPolicy, ...]
    potential_attempts: int | None
    complete: bool
    missing: tuple[str, ...] = ()
    retryable_overlap: tuple[str, ...] = ()
    confidence: Confidence = Confidence.MEDIUM
    unknowns: tuple[UnknownFact, ...] = ()


def amplification(
    hops: tuple[str, ...], policies: tuple[RetryPolicy, ...]
) -> RetryAmplification:
    """§41 multiply declared attempts across a client->dep hop chain.

    `policies` bind to hops by `scope`: an exact hop name, or an
    edge scope `caller->callee` which binds to the caller hop (the
    side that issues retries). A hop with no declared policy lands in
    `missing`; amplification is computed only when every hop declares
    one.
    """
    by_scope = {p.scope: p for p in policies}
    bound: list[RetryPolicy] = []
    missing: list[str] = []
    for hop in hops:
        p = by_scope.get(hop)
        if p is None:
            p = next(
                (
                    cand
                    for cand in sorted(policies, key=lambda x: x.scope)
                    if cand.scope.split("->", 1)[0].strip() == hop
                ),
                None,
            )
        if p is None or p.max_attempts is None:
            missing.append(hop)
        else:
            bound.append(p)
    overlap: set[str] = set()
    declared_sets = [
        set(p.retryable_statuses) for p in bound if p.retryable_statuses
    ]
    if declared_sets and len(declared_sets) == len(bound):
        overlap = set.intersection(*declared_sets) if declared_sets else set()
    complete = not missing and bool(bound)
    total: int | None = None
    if complete:
        total = 1
        for p in bound:
            total *= p.max_attempts or 1
    return RetryAmplification(
        hops=hops,
        policies=tuple(bound),
        potential_attempts=total,
        complete=complete,
        missing=tuple(sorted(missing)),
        retryable_overlap=tuple(sorted(overlap)),
        confidence=Confidence.MEDIUM if complete else Confidence.UNKNOWN,
        unknowns=(
            ()
            if complete
            else tuple(
                UnknownFact(
                    subject=f"hop {hop}",
                    missing="declared retry policy with max_attempts",
                    resolution="amplification is not computed without "
                    "explicit per-hop configs",
                )
                for hop in missing
            )
        ),
    )
