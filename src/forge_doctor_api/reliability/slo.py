"""ApiServiceObjective (§46) + ErrorBudget (§47).

Budgets are computed only with sufficient window data; otherwise the
budget reports `sufficient=False` with `UnknownFact`s instead of a
number nobody should trust.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.history import window_key
from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.perf.stats import MIN_SAMPLES
from forge_doctor_api.reliability.model import (
    ApiServiceObjective,
    ErrorBudget,
)


def error_budget(
    objective: ApiServiceObjective,
    executions: tuple[RequestExecution, ...],
) -> ErrorBudget:
    """§47 consumed/remaining error budget for an objective.

    Only `error_rate`/`availability`-style objectives compute here.
    The budget uses the objective's declared window when present,
    else all windows.
    """
    scoped = [
        e
        for e in executions
        if objective.window is None
        or window_key(e.start_unix_nano) == objective.window
    ]
    window = objective.window or "(all)"
    total = len(scoped)
    if total < MIN_SAMPLES:
        return ErrorBudget(
            objective=objective.name,
            window=window,
            total=total,
            consumed=0.0,
            remaining=0.0,
            sufficient=False,
            unknowns=(
                UnknownFact(
                    subject=objective.name,
                    missing=f">= {MIN_SAMPLES} requests in window {window}",
                    resolution="provide more runtime history for the "
                    "objective window",
                ),
            ),
        )
    errors = sum(
        1
        for e in scoped
        if e.status == "error"
        or ((e.status or "").isdigit() and int(e.status or "0") >= 500)
    )
    allowed = 1.0 - objective.target  # e.g. 0.999 availability -> 0.1%
    budget = allowed * total
    return ErrorBudget(
        objective=objective.name,
        window=window,
        total=total,
        consumed=float(errors),
        remaining=budget - errors,
        sufficient=True,
    )
