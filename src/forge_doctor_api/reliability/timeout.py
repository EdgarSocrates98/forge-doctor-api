"""TimeoutBudget (§43) - caller timeout vs downstream needs.

Sequential downstreams sum; parallel downstreams take the max. When
execution order is unknown, both bounds are computed: impossible only
when even the optimistic (parallel) bound exceeds the budget; the
sequential bound then flags risk explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Model, UnknownFact


class BudgetVerdict(StrEnum):
    FEASIBLE = "FEASIBLE"
    IMPOSSIBLE = "IMPOSSIBLE"
    AT_RISK = "AT_RISK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class TimeoutBudget(Model):
    """§43 budget evaluation for one caller."""

    caller: str
    caller_timeout_ms: float | None
    downstreams: tuple[tuple[str, float | None], ...]
    sequential_need_ms: float | None
    parallel_need_ms: float | None
    verdict: BudgetVerdict
    unknowns: tuple[UnknownFact, ...] = ()


def evaluate_timeout_budget(
    caller: str,
    caller_timeout_ms: float | None,
    downstreams: tuple[tuple[str, float | None], ...],
) -> TimeoutBudget:
    """Compare the caller budget against declared downstream budgets."""
    unknowns: list[UnknownFact] = []
    if caller_timeout_ms is None:
        unknowns.append(
            UnknownFact(
                subject=caller,
                missing="caller timeout budget",
                resolution="declare the caller's timeout in config",
            )
        )
    undetermined = [name for name, ms in downstreams if ms is None]
    for name in undetermined:
        unknowns.append(
            UnknownFact(
                subject=f"downstream {name}",
                missing="downstream timeout budget",
                resolution="declare per-dependency timeouts",
            )
        )
    known = [ms for _, ms in downstreams if ms is not None]
    seq = sum(known) if known else None
    par = max(known) if known else None

    if caller_timeout_ms is None or not known:
        verdict = BudgetVerdict.UNKNOWN
    elif par is not None and par > caller_timeout_ms:
        verdict = BudgetVerdict.IMPOSSIBLE  # even optimistic bound exceeds
    elif seq is not None and seq > caller_timeout_ms:
        verdict = BudgetVerdict.AT_RISK  # exceeds only if sequential
    else:
        verdict = BudgetVerdict.FEASIBLE
    if undetermined and verdict is BudgetVerdict.FEASIBLE:
        verdict = BudgetVerdict.AT_RISK

    return TimeoutBudget(
        caller=caller,
        caller_timeout_ms=caller_timeout_ms,
        downstreams=downstreams,
        sequential_need_ms=seq,
        parallel_need_ms=par,
        verdict=verdict,
        unknowns=tuple(unknowns),
    )
