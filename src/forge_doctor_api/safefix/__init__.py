"""§104 safe-fix classification — SAFE / REVIEW_REQUIRED / MANUAL_ONLY."""

from forge_doctor_api.safefix.classify import (
    classify_finding,
    classify_findings,
    classify_fix,
)
from forge_doctor_api.safefix.model import (
    FixClass,
    FixType,
    Remediation,
    RemediationReport,
)
from forge_doctor_api.safefix.rules import classify_types, fix_types_for, justification

__all__ = [
    "FixClass",
    "FixType",
    "Remediation",
    "RemediationReport",
    "classify_finding",
    "classify_findings",
    "classify_fix",
    "classify_types",
    "fix_types_for",
    "justification",
]
