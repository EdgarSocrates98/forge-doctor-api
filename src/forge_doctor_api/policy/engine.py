"""§105 POLICY### evaluation — declarative rules -> findings.

Missing policy config produces no findings (no invented org rules).
Exceptions suppress violations only when valid (not expired, approved);
invalid exceptions are themselves findings.
"""

from __future__ import annotations

from datetime import date

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Finding,
    Severity,
    UnknownFact,
)
from forge_doctor_api.policy.loader import (
    exception_validity,
    resolve_policies,
    valid_exception,
)
from forge_doctor_api.policy.model import ApiPolicy, PolicySet
from forge_doctor_api.policy.rules import RULES, PolicyViolation, RuleContext

_SPECS: dict[str, tuple[str, Severity]] = {
    "POLICY008": ("Policy exception invalid or expired", Severity.MEDIUM),
    "POLICY009": ("Policy widened without a valid exception", Severity.HIGH),
    "POLICY010": ("Policy file issue", Severity.LOW),
}


def _finding(check_id: str, title: str, description: str,
             severity: Severity, policy: ApiPolicy | None,
             violation: PolicyViolation | None) -> Finding:
    loc = violation.location if violation else (policy.location if policy else None)
    return Finding(
        id=check_id,
        title=title,
        description=description,
        severity=severity,
        confidence=Confidence.HIGH if severity is not Severity.INFO else Confidence.LOW,
        evidence_kind=EvidenceKind.CONFIG,
        evidence=violation.evidence if violation else (),
        source_location=loc,
        unknowns=(
            UnknownFact(
                subject=violation.subject if violation else "policy",
                missing=description,
                resolution="provide the missing evidence or fix the violation",
            ),
        )
        if severity is Severity.INFO else (),
    )


def evaluate_policies(
    policy_set: PolicySet,
    ctx: RuleContext,
    today: date,
) -> tuple[Finding, ...]:
    """Evaluate resolved policies against the model context -> POLICY### findings."""
    findings: list[Finding] = []

    # malformed/empty policies → issues become findings
    for issue in policy_set.issues:
        title, sev = _SPECS["POLICY010"]
        findings.append(_finding("POLICY010", title, issue, sev, None, None))

    # invalid exceptions → findings; never silently honored
    for exc in policy_set.exceptions:
        reason = exception_validity(exc, today)
        if reason is not None:
            title, sev = _SPECS["POLICY008"]
            findings.append(_finding(
                "POLICY008", title,
                f"exception for rule `{exc.rule}` (scope {exc.scope}) invalid: {reason}",
                sev, None, None,
            ))

    effective, widening_issues = resolve_policies(
        policy_set.policies, policy_set.exceptions, today
    )
    for issue in widening_issues:
        title, sev = _SPECS["POLICY009"]
        findings.append(_finding("POLICY009", title, issue, sev, None, None))

    for policy in effective:
        if not policy.enabled:
            continue
        spec = RULES.get(policy.rule)
        if spec is None:
            continue
        violations = spec.predicate(ctx, policy)
        for v in violations:
            covered = any(
                e.rule == policy.rule and e.covers(v.subject) and valid_exception(e, today)
                for e in policy_set.exceptions
            )
            if covered:
                continue
            sev = policy.severity or spec.default_severity
            findings.append(_finding(
                spec.check_id, spec.title,
                f"{v.detail} [{policy.level.value} policy {policy.id} in {policy.file}]",
                sev, policy, v,
            ))
    findings.sort(
        key=lambda f: (f.id, f.source_location.path if f.source_location else "", f.description)
    )
    return tuple(findings)
