"""Safe-fix classification tests (spec 022, §104).

Positive: each §104 member class reachable via real check ids. Boundary:
combined fixes escalate to the strictest class. Default-deny: unmapped fix
types and unknown check ids are MANUAL_ONLY. Determinism: same findings in,
same report out. Justifications come from the rule table, not free-form.
"""

from __future__ import annotations

from typing import Any

from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
)
from forge_doctor_api.safefix import (
    FixClass,
    FixType,
    classify_findings,
    classify_fix,
    classify_types,
    fix_types_for,
)


def _finding(check_id: str, **overrides: Any) -> Finding:
    values: dict[str, Any] = {
        "id": check_id,
        "title": f"title for {check_id}",
        "description": f"description for {check_id}",
        "severity": Severity.MEDIUM,
        "confidence": Confidence.HIGH,
        "evidence_kind": EvidenceKind.STATIC,
        "entity_ids": ("operation:openapi:op",),
        "source_location": SourceLocation(path="api.yaml", line=3),
        "remediation": "fix it",
    }
    values.update(overrides)
    return Finding(**values)


# -- §104 classes over real check ids -------------------------------------------


def test_safe_members() -> None:
    for check_id in ("OAS001", "OAS003", "OAS004", "OAS005", "OAS009",
                     "OAS014", "OAS015", "OAS018", "OAS020"):
        assert fix_types_for(check_id)
        report = classify_findings((_finding(check_id),))
        c = report.candidates[0]
        assert c.classification is FixClass.SAFE, check_id
        assert c.finding_id == check_id
        assert c.justification  # generated, non-empty


def test_review_required_members() -> None:
    for check_id in ("RELAPI001", "RELAPI003", "RELAPI004",
                     "APIPERF004", "APIPERF005", "APIPERF008"):
        c = classify_findings((_finding(check_id),)).candidates[0]
        assert c.classification is FixClass.REVIEW_REQUIRED, check_id
        # REVIEW_REQUIRED justification names the reviewer-relevant risk
        assert any(
            word in c.justification
            for word in ("load", "latency", "freshness", "amplification", "paging")
        )


def test_manual_only_members() -> None:
    for check_id in ("OAS010", "OAS012", "OAS016", "OAS017",
                     "APISEC001", "APISEC003", "APISEC005", "APISEC008"):
        c = classify_findings((_finding(check_id),)).candidates[0]
        assert c.classification is FixClass.MANUAL_ONLY, check_id


def test_api_perview_combined_types_stay_manual() -> None:
    """APISEC006 maps to pagination+rate-limit — strictest class wins."""
    types = fix_types_for("APISEC006")
    assert set(types) == {FixType.PAGINATION_DEFAULT, FixType.RATE_LIMIT}
    assert classify_types(types) is FixClass.MANUAL_ONLY


def test_default_deny_unmapped() -> None:
    """Unmapped check ids and UNMAPPED types are MANUAL_ONLY, never guessed."""
    for check_id in ("COMPAT007", "DRIFT001", "CLIENT002", "OBSAPI001", "ZZZ999"):
        c = classify_findings((_finding(check_id),)).candidates[0]
        assert c.classification is FixClass.MANUAL_ONLY, check_id
        assert c.fix_types == (FixType.UNMAPPED,)
    assert classify_types(()) is FixClass.MANUAL_ONLY
    assert classify_types((FixType.UNMAPPED,)) is FixClass.MANUAL_ONLY


def test_combined_fix_escalates_to_strictest() -> None:
    """timeout+cache combined -> REVIEW; timeout+auth combined -> MANUAL_ONLY."""
    assert classify_types((FixType.TIMEOUT, FixType.CACHE)) is FixClass.REVIEW_REQUIRED
    assert classify_types((FixType.TIMEOUT, FixType.AUTH)) is FixClass.MANUAL_ONLY
    assert classify_types((FixType.METADATA_MISSING, FixType.DOC_FIELD)) is FixClass.SAFE
    fix = classify_fix(
        "retune timeout and auth together", "gw",
        (FixType.TIMEOUT, FixType.AUTHORIZATION),
    )
    assert fix.classification is FixClass.MANUAL_ONLY
    assert "authorization" in fix.justification


def test_justification_from_rule_table() -> None:
    fix = classify_fix("rename key", "cfg", (FixType.DEPRECATED_CONFIG_RENAME,))
    assert fix.justification == "deprecated key rename — no behavior change"


def test_report_grouping_and_determinism() -> None:
    findings = (
        _finding("APISEC001"),   # MANUAL
        _finding("OAS004"),      # SAFE
        _finding("RELAPI001"),   # REVIEW
        _finding("OAS020"),      # SAFE
    )
    r1 = classify_findings(findings)
    r2 = classify_findings(findings)
    assert [c.finding_id for c in r1.candidates] == [c.finding_id for c in r2.candidates]
    assert tuple(c.finding_id for c in r1.by_class(FixClass.SAFE)) == ("OAS004", "OAS020")
    assert tuple(c.finding_id for c in r1.by_class(FixClass.REVIEW_REQUIRED)) == ("RELAPI001",)
    assert tuple(c.finding_id for c in r1.by_class(FixClass.MANUAL_ONLY)) == ("APISEC001",)


def test_remediation_serializes_with_evidence() -> None:
    f = _finding("OAS015", evidence=(Evidence(
        kind=EvidenceKind.STATIC, source="api.yaml", summary="deprecated without sunset",
        line=7,
    ),))
    c = classify_findings((f,)).candidates[0]
    d = c.to_dict()
    assert d["classification"] == "SAFE"
    assert d["evidence"][0]["source"] == "api.yaml"
    assert c.location is not None and c.location.line == 3  # finding source_location
