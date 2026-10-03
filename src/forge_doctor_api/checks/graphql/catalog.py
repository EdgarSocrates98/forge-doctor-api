"""GQL### check catalog (§23)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)


@dataclass(frozen=True, kw_only=True)
class GqlCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[GqlCheckSpec, ...] = (
    GqlCheckSpec(
        id="GQL001",
        title="Deprecated field with active clients",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A deprecated schema field is still selected by a "
        "parsed client query (§184).",
    ),
    GqlCheckSpec(
        id="GQL002",
        title="Field removed",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A field present in the old schema is absent in the new.",
    ),
    GqlCheckSpec(
        id="GQL003",
        title="Required argument added",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A non-null argument without default was added to an "
        "existing field (request-side breaking).",
    ),
    GqlCheckSpec(
        id="GQL004",
        title="Nullable became non-null",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A type ref changed nullable -> non-null; classified "
        "per §123 input/output position polarity.",
    ),
    GqlCheckSpec(
        id="GQL005",
        title="Enum value removed",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="An enum value was removed; producers may still emit it.",
    ),
    GqlCheckSpec(
        id="GQL006",
        title="Resolver without authorization evidence",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="A resolvable field has no auth directive evidence; "
        "enforcement may still happen in code or middleware - candidate.",
    ),
    GqlCheckSpec(
        id="GQL007",
        title="Potentially unbounded list field",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="A list-typed field has no pagination arguments "
        "(first/last/after/limit/offset) - candidate.",
    ),
    GqlCheckSpec(
        id="GQL008",
        title="Deep traversal candidate",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="The type graph admits recursive traversal or a parsed "
        "client query exceeds the transparency depth threshold (5).",
    ),
    GqlCheckSpec(
        id="GQL009",
        title="N+1 candidate",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="A list field's element type has sub-object fields - "
        "STATIC candidate until RUNTIME evidence confirms (§102).",
    ),
    GqlCheckSpec(
        id="GQL010",
        title="Introspection exposure policy mismatch",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="Config evidence enables introspection, or no "
        "introspection policy evidence exists - candidate.",
    ),
)

BY_ID: dict[str, GqlCheckSpec] = {c.id: c for c in CATALOG}
