"""CLIENT### check catalog (§17, §68, §183, §218)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Confidence, EvidenceKind, Severity


@dataclass(frozen=True)
class ClientCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    trigger: str


CATALOG: tuple[ClientCheckSpec, ...] = (
    ClientCheckSpec(
        "CLIENT001", "Confirmed client impact", Severity.HIGH, Confidence.HIGH,
        EvidenceKind.STATIC,
        "A breaking contract change touches an element a known client "
        "statically reads (§183).",
    ),
    ClientCheckSpec(
        "CLIENT002", "Client in blast radius", Severity.MEDIUM, Confidence.MEDIUM,
        EvidenceKind.STATIC,
        "A known client consumes an operation that changed; no field-level "
        "usage proves impact.",
    ),
    ClientCheckSpec(
        "CLIENT003", "Unresolvable client call site", Severity.LOW, Confidence.LOW,
        EvidenceKind.STATIC,
        "An HTTP client call has a dynamic URL/method that cannot be mapped "
        "to the contract; it may or may not consume a changed operation.",
    ),
)

BY_ID: dict[str, ClientCheckSpec] = {spec.id: spec for spec in CATALOG}
