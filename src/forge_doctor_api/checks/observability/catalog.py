"""OBSAPI### check catalog (§85)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)


@dataclass(frozen=True, kw_only=True)
class ObsCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[ObsCheckSpec, ...] = (
    ObsCheckSpec(
        id="OBSAPI001",
        title="Missing request correlation evidence",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Runtime artifacts lack correlation-id/request-id/"
        "traceparent evidence — candidate.",
    ),
    ObsCheckSpec(
        id="OBSAPI002",
        title="Trace propagation gap",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Spans exist but parent linkage/propagation headers "
        "are absent — candidate.",
    ),
    ObsCheckSpec(
        id="OBSAPI003",
        title="Inconsistent operation naming",
        severity=Severity.LOW,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Operation names mix naming conventions "
        "(camelCase/snake_case/kebab-case).",
    ),
    ObsCheckSpec(
        id="OBSAPI004",
        title="Error without structured context",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Error-status spans lack error attributes — candidate.",
    ),
    ObsCheckSpec(
        id="OBSAPI005",
        title="Missing latency metrics for critical operation",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Spans lack duration data — candidate.",
    ),
)

BY_ID: dict[str, ObsCheckSpec] = {c.id: c for c in CATALOG}
