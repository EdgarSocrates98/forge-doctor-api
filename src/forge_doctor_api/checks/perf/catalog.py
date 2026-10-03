"""APIPERF### check catalog (§37, §89)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)


@dataclass(frozen=True, kw_only=True)
class PerfCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[PerfCheckSpec, ...] = (
    PerfCheckSpec(
        id="APIPERF001",
        title="p95 latency regression",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.DERIVED,
        description="Current-window p95 exceeds baseline p95 beyond the "
        "declared MAD/factor threshold.",
    ),
    PerfCheckSpec(
        id="APIPERF002",
        title="Error-rate regression",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.DERIVED,
        description="Current-window error rate exceeds baseline beyond "
        "the declared threshold.",
    ),
    PerfCheckSpec(
        id="APIPERF003",
        title="Downstream latency regression",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.DERIVED,
        description="Downstream-call p95 to a callee regressed beyond "
        "the declared threshold.",
    ),
    PerfCheckSpec(
        id="APIPERF004",
        title="Retry amplification",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Observed retry rate increased vs baseline - "
        "candidate.",
    ),
    PerfCheckSpec(
        id="APIPERF005",
        title="Timeout increase",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.DERIVED,
        description="Observed timeout rate increased vs baseline - "
        "candidate.",
    ),
    PerfCheckSpec(
        id="APIPERF006",
        title="Payload growth",
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.DERIVED,
        description="Response payload p95 grew beyond the declared "
        "threshold.",
    ),
    PerfCheckSpec(
        id="APIPERF007",
        title="Fan-out increase",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.DERIVED,
        description="Mean downstream fan-out per request increased - "
        "candidate.",
    ),
    PerfCheckSpec(
        id="APIPERF008",
        title="Cache effectiveness regression",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.RUNTIME,
        description="Observed cache-hit rate declined vs baseline - "
        "candidate.",
    ),
)

BY_ID: dict[str, PerfCheckSpec] = {c.id: c for c in CATALOG}
