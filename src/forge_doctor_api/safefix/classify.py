"""§104 classifier — attach remediation candidates to findings."""

from __future__ import annotations

from forge_doctor_api.core.models import Finding
from forge_doctor_api.safefix.model import (
    FixClass,
    FixType,
    Remediation,
    RemediationReport,
)
from forge_doctor_api.safefix.rules import classify_types, fix_types_for, justification


def classify_fix(
    proposed_change: str, target: str, fix_types: tuple[FixType, ...]
) -> Remediation:
    """Classify a proposed change — combined types escalate to strictest."""
    return Remediation(
        proposed_change=proposed_change,
        target=target,
        classification=classify_types(tuple(fix_types)),
        justification=justification(tuple(fix_types)),
        fix_types=tuple(fix_types),
    )


def classify_finding(finding: Finding) -> Remediation:
    """Map one finding to a remediation candidate (deterministic table)."""
    types = fix_types_for(finding.id)
    subject = finding.entity_ids[0] if finding.entity_ids else finding.title
    return Remediation(
        proposed_change=finding.remediation or finding.title,
        target=subject,
        classification=classify_types(types),
        justification=justification(types),
        fix_types=types,
        finding_id=finding.id,
        location=finding.source_location,
        evidence=finding.evidence,
        unknowns=finding.unknowns,
    )


def classify_findings(findings: tuple[Finding, ...]) -> RemediationReport:
    """Classify all findings — output groups by class, deterministic order."""
    candidates = tuple(classify_finding(f) for f in findings)
    order = {FixClass.SAFE: 0, FixClass.REVIEW_REQUIRED: 1, FixClass.MANUAL_ONLY: 2}
    ordered = tuple(
        sorted(candidates, key=lambda c: (order[c.classification], c.target))
    )
    return RemediationReport(candidates=ordered)
