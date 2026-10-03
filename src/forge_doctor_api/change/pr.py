"""§67 PR intelligence summary — six counters, Unknowns never dropped."""

from __future__ import annotations

from forge_doctor_api.change.model import ChangeEvent, ChangeType, PrIntelSummary
from forge_doctor_api.checks.compat import CompatibilityClass
from forge_doctor_api.reliability.model import ApiReliabilityModel


def pr_summary(
    events: tuple[ChangeEvent, ...],
    *,
    affected_clients: tuple[str, ...] = (),
    reliability: ApiReliabilityModel | None = None,
    extra_unknowns: int = 0,
) -> PrIntelSummary:
    """Build the §67 counter summary.

    - `affected_clients`: distinct consuming identities from blast radius.
    - `reliability`: used to judge SLO relevance of dependency/config
      changes — a change to a scope matching a declared objective name is
      SLO-relevant; external dependency changes are always SLO-relevant.
    - `extra_unknowns`: unknowns from inputs that produced no event
      (e.g. malformed contract documents) — counted, never dropped.
    """
    breaking = sum(
        1 for e in events if e.classification is CompatibilityClass.BREAKING
    )
    new_endpoints = sum(1 for e in events if e.type is ChangeType.ENDPOINT_ADDED)
    auth = sum(1 for e in events if e.type is ChangeType.AUTH_CHANGED)

    objective_names = frozenset(
        o.name for o in reliability.objectives
    ) if reliability is not None else frozenset()
    slo_relevant = sum(
        1
        for e in events
        if e.type is ChangeType.DEPENDENCY_CHANGED
        or (
            e.type
            in (ChangeType.TIMEOUT_CHANGED, ChangeType.RETRY_CHANGED, ChangeType.RATE_LIMIT_CHANGED)
            and e.subject in objective_names
        )
    )

    unknown_events = sum(
        1 for e in events if e.classification is CompatibilityClass.UNKNOWN
    )
    return PrIntelSummary(
        breaking_changes=breaking,
        affected_clients=len(set(affected_clients)),
        new_public_endpoints=new_endpoints,
        authorization_changes=auth,
        slo_relevant_dependency_changes=slo_relevant,
        unknowns=unknown_events + extra_unknowns,
    )
