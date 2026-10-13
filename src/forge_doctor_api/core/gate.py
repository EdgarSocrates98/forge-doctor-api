"""§178 CI gate semantics — categories, failures, evaluation.

Gate types live in core so the unified report (`core.report`) can carry
them without layering cycles. `evaluate_gate` applies the §178 fail-on
categories; findings at Confidence.UNKNOWN never block a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.core.models import (
    Confidence,
    Finding,
    Model,
    check_namespace,
)


class GateCategory(StrEnum):
    """§178 configurable gate categories."""

    BREAKING = "breaking"
    SECURITY = "security"
    POLICY = "policy"


@dataclass(frozen=True, kw_only=True)
class GateFailure(Model):
    """One §178 gate trigger: category + evidence-bearing subjects."""

    category: GateCategory
    subjects: tuple[str, ...]
    detail: str


_CONF_RANK = {
    Confidence.UNKNOWN: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


def _findings_of(namespace: str, findings: tuple[Finding, ...],
                 min_confidence: Confidence) -> tuple[str, ...]:
    return tuple(
        f"{f.id}: {f.description}"
        for f in findings
        if check_namespace(f.id) == namespace
        and f.confidence is not Confidence.UNKNOWN
        and _CONF_RANK[f.confidence] >= _CONF_RANK[min_confidence]
    )


class GateConfigError(ValueError):
    """fail-on category requested without the inputs it needs."""


def evaluate_gate(
    findings: tuple[Finding, ...],
    diff: ContractDiff | None,
    fail_on: frozenset[GateCategory],
) -> tuple[GateFailure, ...]:
    """§178 — UNKNOWN-confidence findings never produce a failure."""
    failures: list[GateFailure] = []
    if GateCategory.BREAKING in fail_on:
        if diff is None:
            raise GateConfigError(
                "fail-on=breaking requires a --baseline contract context")
        breaking = tuple(
            f"{c.kind}: {c.subject} {c.path}".strip()
            for c in diff.changes
            if c.classification is CompatibilityClass.BREAKING
        )
        if breaking:
            failures.append(GateFailure(
                category=GateCategory.BREAKING,
                subjects=breaking,
                detail=f"{len(breaking)} breaking change(s) detected",
            ))
    if GateCategory.SECURITY in fail_on:
        hits = _findings_of("APISEC", findings, Confidence.HIGH)
        if hits:
            failures.append(GateFailure(
                category=GateCategory.SECURITY,
                subjects=hits,
                detail=f"{len(hits)} high-confidence security issue(s)",
            ))
    if GateCategory.POLICY in fail_on:
        hits = _findings_of("POLICY", findings, Confidence.LOW)
        if hits:
            failures.append(GateFailure(
                category=GateCategory.POLICY,
                subjects=hits,
                detail=f"{len(hits)} policy violation(s)",
            ))
    return tuple(failures)
