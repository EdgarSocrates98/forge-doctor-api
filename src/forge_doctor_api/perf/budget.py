"""ApiLatencyBudget (§154) + SLO critical-path linkage (§155)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Model, UnknownFact
from forge_doctor_api.perf.criticalpath import RequestCriticalPath


@dataclass(frozen=True, kw_only=True)
class BudgetHop(Model):
    """One hop in the §154 chain (client/gateway/service/dependency)."""

    name: str
    budget_ms: float | None = None


@dataclass(frozen=True, kw_only=True)
class ApiLatencyBudget(Model):
    """§154 ordered hop budgets along a request path."""

    name: str
    hops: tuple[BudgetHop, ...]
    total_ms: float | None = None


@dataclass(frozen=True, kw_only=True)
class BudgetHopReport(Model):
    hop: str
    observed_ms: float | None
    budget_ms: float | None
    over_budget: bool | None


@dataclass(frozen=True, kw_only=True)
class BudgetReport(Model):
    """§155 linkage: critical-path segments evaluated against budget."""

    budget: str
    trace_id: str
    hops: tuple[BudgetHopReport, ...]
    within_budget: bool | None
    unknowns: tuple[UnknownFact, ...] = ()


def evaluate_budget(
    path: RequestCriticalPath, budget: ApiLatencyBudget
) -> BudgetReport:
    """Match budget hops to critical-path segments by name.

    `service:<name>` and `downstream:<name>` segment labels match a hop
    named `<name>`; `auth`/`serialization` match same-named hops. Hops
    with no segment or no budget stay `over_budget=None`.
    """
    by_label = {s.label: s for s in path.segments}
    reports: list[BudgetHopReport] = []
    unknowns: list[UnknownFact] = []
    for hop in budget.hops:
        seg = None
        for label in (f"service:{hop.name}", f"downstream:{hop.name}", hop.name):
            if label in by_label:
                seg = by_label[label]
                break
        observed = seg.duration_ms if seg else None
        over = (
            observed > hop.budget_ms
            if observed is not None and hop.budget_ms is not None
            else None
        )
        if over is None:
            unknowns.append(
                UnknownFact(
                    subject=f"hop {hop.name}",
                    missing=(
                        "observed segment" if seg is None else "hop budget"
                    ),
                    resolution="provide a budget_ms value or a trace "
                    "covering this hop",
                )
            )
        reports.append(
            BudgetHopReport(
                hop=hop.name,
                observed_ms=observed,
                budget_ms=hop.budget_ms,
                over_budget=over,
            )
        )
    known = [r for r in reports if r.over_budget is not None]
    within = (
        all(not r.over_budget for r in known) if known else None
    )
    return BudgetReport(
        budget=budget.name,
        trace_id=path.trace_id,
        hops=tuple(reports),
        within_budget=within,
        unknowns=tuple(unknowns),
    )
