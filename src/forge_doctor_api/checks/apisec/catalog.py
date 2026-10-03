"""APISEC### check catalog (§50, §218).

Every check maps to OWASP API Top 10 (2023) categories via the bundled
knowledge pack - `forge_doctor_api.security.knowledge.check_to_owasp`
resolves the mapping, so category updates need no code change.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)
from forge_doctor_api.security.model import FindingClass


@dataclass(frozen=True, kw_only=True)
class SecCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    finding_class: FindingClass
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[SecCheckSpec, ...] = (
    SecCheckSpec(
        id="APISEC001",
        title="Object-ID route without authorization evidence",
        severity=Severity.HIGH,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Path with an object-identifier parameter and no "
        "object-level authorization evidence - BOLA risk candidate.",
    ),
    SecCheckSpec(
        id="APISEC002",
        title="Admin operation without explicit authorization",
        severity=Severity.HIGH,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Operation under an admin-marked path/identity with "
        "no declared roles/scopes - function-level authz candidate.",
    ),
    SecCheckSpec(
        id="APISEC003",
        title="Unauthenticated sensitive operation",
        severity=Severity.HIGH,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Anonymous-allowed operation explicitly marked "
        "sensitive via metadata - authentication candidate.",
    ),
    SecCheckSpec(
        id="APISEC004",
        title="Wildcard CORS",
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.CONFIG,
        finding_class=FindingClass.CONFIGURATION_RISK,
        description="CORS allows any origin; with credentials it is a "
        "configuration risk.",
    ),
    SecCheckSpec(
        id="APISEC005",
        title="Missing rate-limit evidence on public operation",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Anonymous-allowed operation with no declared "
        "rate-limit policy covering it - candidate.",
    ),
    SecCheckSpec(
        id="APISEC006",
        title="Unrestricted expensive operation",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Collection-returning operation with no pagination "
        "and no resource bound - candidate.",
    ),
    SecCheckSpec(
        id="APISEC007",
        title="Unsafe outbound URL consumption",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Operation accepts a URL-shaped parameter that may "
        "feed server-side fetch - SSRF candidate.",
    ),
    SecCheckSpec(
        id="APISEC008",
        title="Sensitive property exposed in response",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CANDIDATE,
        description="Response schema contains a property explicitly "
        "classified as sensitive - exposure candidate.",
    ),
    SecCheckSpec(
        id="APISEC009",
        title="Deprecated API still reachable",
        severity=Severity.LOW,
        confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        finding_class=FindingClass.CONFIGURATION_RISK,
        description="Operation marked deprecated remains documented as "
        "reachable - inventory-management risk.",
    ),
    SecCheckSpec(
        id="APISEC010",
        title="Unsafe third-party API dependency",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        finding_class=FindingClass.CONFIGURATION_RISK,
        description="External API dependency without timeout/auth "
        "evidence - unsafe-consumption configuration risk.",
    ),
)

BY_ID: dict[str, SecCheckSpec] = {c.id: c for c in CATALOG}
