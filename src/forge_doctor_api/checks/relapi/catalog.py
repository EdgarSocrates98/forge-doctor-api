"""RELAPI### check catalog (§218)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)


@dataclass(frozen=True, kw_only=True)
class RelCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[RelCheckSpec, ...] = (
    RelCheckSpec(
        id="RELAPI001",
        title="Retry amplification candidate",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.CONFIG,
        description="Stacked explicit retry policies multiply potential "
        "attempts along a path.",
    ),
    RelCheckSpec(
        id="RELAPI002",
        title="Idempotency unknown on retried operation",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        description="A retried scope has no idempotency evidence - "
        "manual review required.",
    ),
    RelCheckSpec(
        id="RELAPI003",
        title="Impossible timeout budget",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.CONFIG,
        description="Declared downstream budgets exceed the caller "
        "timeout even under parallel execution.",
    ),
    RelCheckSpec(
        id="RELAPI004",
        title="Deadline propagation gap",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        description="Call-chain hop lacks deadline/timeout propagation "
        "evidence - candidate.",
    ),
    RelCheckSpec(
        id="RELAPI005",
        title="No circuit breaker evidence",
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        description="Retry/timeout evidence exists but no declared "
        "circuit breaker - candidate.",
    ),
    RelCheckSpec(
        id="RELAPI006",
        title="No health check evidence",
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        description="Service/API evidence exists but no declared health "
        "check - candidate.",
    ),
    RelCheckSpec(
        id="RELAPI007",
        title="No graceful shutdown evidence",
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        description="No graceful-shutdown/drain configuration evidence - "
        "candidate.",
    ),
)

BY_ID: dict[str, RelCheckSpec] = {c.id: c for c in CATALOG}
