"""Spec 074 — forge-contracts/1 wire conformance.

The API Doctor speaks the shared wire vocabulary without importing the
Data Doctor package. These tests prove:

- the canonical fixture (a real forge-contracts/1 payload produced by
  the sibling doctor) decodes through our wire types and re-emits to
  the same contract shape;
- adapters map every core model to schema-valid wire payloads, with
  API-specific fields under ``x-forge-api`` only;
- the validator enforces required fields, enums and types;
- ``x-*`` extensions round-trip (forward payloads survive older readers);
- no ``forge_doctor_data`` import exists anywhere in src/ or tests/.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from forge_doctor_api.contracts import (
    API_EXTENSION,
    FORGE_CONTRACT_SCHEMAS,
    ContractError,
    ContractVersion,
    Entity,
    HandoffBundle,
    UnknownFact,
    assert_valid,
    entity_from_id,
    negotiate,
    report_handoff,
    report_manifest,
    validate_named,
    wire_capability,
    wire_capability_gap,
    wire_edge_export,
    wire_entity,
    wire_finding,
    wire_relationship,
    wire_unknown,
    within_range,
)
from forge_doctor_api.contracts import Finding as WireFinding
from forge_doctor_api.core.graph import EdgeExport
from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    SourceLocation,
)
from forge_doctor_api.core.models import (
    Entity as CoreEntity,
)
from forge_doctor_api.core.models import (
    Evidence as CoreEvidence,
)
from forge_doctor_api.core.models import (
    Finding as CoreFinding,
)
from forge_doctor_api.core.models import (
    Relationship as CoreRelationship,
)
from forge_doctor_api.core.models import (
    UnknownFact as CoreUnknown,
)
from forge_doctor_api.knowledge.capability import (
    Capability as CapabilityKind,
)
from forge_doctor_api.knowledge.capability import (
    CapabilityGap,
    DependencyRule,
    DetectedCapability,
)
from forge_doctor_api.report import DoctorReport

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "contracts"
    / "forge-contracts-1-handoff.json"
)


def _core_finding(**kw: object) -> CoreFinding:
    defaults: dict[str, object] = {
        "id": "OAS001",
        "title": "Operation missing description",
        "description": "GET /pets has no description",
        "severity": Severity.HIGH,
        "confidence": Confidence.MEDIUM,
        "evidence_kind": EvidenceKind.STATIC,
        "evidence": (
            CoreEvidence(
                kind=EvidenceKind.STATIC,
                source="api.yaml",
                summary="GET /pets operation",
                line=12,
            ),
        ),
        "entity_ids": ("operation:openapi:get /pets",),
        "source_location": SourceLocation(path="api.yaml", line=12),
        "remediation": "Add a description to the operation.",
    }
    defaults.update(kw)
    return CoreFinding(**defaults)  # type: ignore[arg-type]


# -- canonical fixture round-trip ---------------------------------------------

def test_canonical_fixture_decodes() -> None:
    """A real forge-contracts/1 payload from the sibling doctor parses."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bundle = HandoffBundle.from_dict(payload)
    assert bundle.contract_version == "forge-contracts/1"
    assert bundle.tool == "forge-doctor-data"
    assert len(bundle.findings) == 1
    assert bundle.findings[0].check_id == "FD-DBT-042"
    assert bundle.findings[0].severity == "warning"
    assert len(bundle.entities) == 1
    assert bundle.entities[0].kind == "model"
    assert len(bundle.relationships) == 1
    assert len(bundle.capabilities) == 1
    assert len(bundle.plans) == 1
    assert len(bundle.unknowns) == 1
    assert bundle.unknowns[0].reason == "no collector"


def test_canonical_fixture_validates_against_schema() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert validate_named(payload, "handoff") == []


def test_canonical_fixture_reemits_valid() -> None:
    """Decode -> re-emit stays conforming (cross-doctor round trip)."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bundle = HandoffBundle.from_dict(payload)
    assert validate_named(bundle.to_dict(), "handoff") == []


def test_every_schema_entry_validates_minimal_payload() -> None:
    """Each published schema accepts a minimal-but-valid payload."""
    minimal: dict[str, dict] = {
        "entity": {"id": "a:b:c", "kind": "a", "domain": "b"},
        "relationship": {"src": "a:b:c", "dst": "a:b:d", "kind": "CALLS"},
        "evidence": {"ref": "f:1", "kind": "static", "source": "t"},
        "finding": {
            "check_id": "X001", "title": "t", "severity": "info",
            "category": "c", "message": "m"},
        "capability": {"id": "C", "domain": "api", "status": "supported"},
        "unknown-fact": {
            "subject": "s", "kind": "evidence", "reason": "missing"},
        "migration-plan": {
            "id": "m1", "source": "a", "target": "b", "kind": "k"},
        "remediation-plan": {
            "id": "r1", "check_id": "X001", "problem": "p"},
        "handoff": {
            "tool": {"name": "t", "version": "0"},
            "project": {}, "summary": {}},
        "diagnostic-manifest": {"tool": {"name": "t", "version": "0"}},
    }
    for kind, payload in minimal.items():
        errors = validate_named(payload, kind)
        assert errors == [], f"{kind}: {errors}"


# -- validators ----------------------------------------------------------------

def test_validator_rejects_missing_required() -> None:
    errors = validate_named({"kind": "a", "domain": "b"}, "entity")
    assert any("id" in e for e in errors)


def test_validator_rejects_null_required() -> None:
    errors = validate_named(
        {"id": None, "kind": "a", "domain": "b"}, "entity")
    assert any("id" in e and "null" in e for e in errors)


def test_validator_rejects_bad_enum() -> None:
    errors = validate_named(
        {"check_id": "X", "title": "t", "severity": "severe",
         "category": "c", "message": "m"},
        "finding")
    assert any("enum" in e for e in errors)


def test_validator_rejects_wrong_type() -> None:
    errors = validate_named(
        {"id": "a:b:c", "kind": "a", "domain": "b", "line": "twelve"},
        "entity")
    assert any("line" in e for e in errors)


def test_validator_nested_items() -> None:
    payload = {
        "tool": {"name": "t", "version": "0"},
        "project": {}, "summary": {},
        "findings": [{"check_id": "X001"}],  # missing required fields
    }
    errors = validate_named(payload, "handoff")
    assert any("findings[0]" in e for e in errors)


def test_assert_valid_raises_with_all_errors() -> None:
    with pytest.raises(ContractError) as exc:
        assert_valid({"kind": "a"}, "entity")
    assert "id" in str(exc.value)


def test_contract_version_pattern_enforced() -> None:
    errors = validate_named(
        {"contract_version": "bogus/7",
         "id": "a:b:c", "kind": "a", "domain": "b"},
        "entity")
    assert any("contract_version" in e for e in errors)


# -- x-* extension round trip ---------------------------------------------------

def test_x_extension_round_trips() -> None:
    payload = {
        "contract_version": "forge-contracts/1",
        "id": "a:b:c", "kind": "a", "domain": "b",
        "x-future-field": {"nested": [1, 2]},
    }
    entity = Entity.from_dict(payload)
    assert entity.extensions["x-future-field"] == {"nested": [1, 2]}
    out = entity.to_dict()
    assert out["x-future-field"] == {"nested": [1, 2]}
    assert validate_named(out, "entity") == []


def test_forge_api_extension_round_trips() -> None:
    f = wire_finding(_core_finding())
    out = f.to_dict()
    assert out[API_EXTENSION]["entity_ids"] == ["operation:openapi:get /pets"]
    decoded = WireFinding.from_dict(out)
    assert decoded.extensions[API_EXTENSION]["entity_ids"] == [
        "operation:openapi:get /pets"]


# -- adapters -------------------------------------------------------------------

def test_wire_finding_maps_severity_and_fields() -> None:
    f = wire_finding(_core_finding(severity=Severity.CRITICAL))
    d = f.to_dict()
    assert d["severity"] == "error"
    assert d["check_id"] == "OAS001"
    assert d["category"] == "oas"
    assert d["file"] == "api.yaml"
    assert d["line"] == 12
    assert d["confidence"] == "medium"
    assert d["evidence_kind"] == "static"
    assert d["source"] == "forge-doctor-api"
    assert validate_named(d, "finding") == []


@pytest.mark.parametrize("sev,expected", [
    (Severity.CRITICAL, "error"), (Severity.HIGH, "error"),
    (Severity.MEDIUM, "warning"), (Severity.LOW, "info"),
    (Severity.INFO, "info"),
])
def test_severity_map(sev: Severity, expected: str) -> None:
    assert wire_finding(_core_finding(severity=sev)).severity == expected


def test_wire_entity_decomposes_canonical_id() -> None:
    e = wire_entity(CoreEntity(
        id="operation:openapi:get /pets", kind="operation",
        name="get /pets",
        attributes={"file": "api.yaml", "line": "7"}))
    d = e.to_dict()
    assert d["id"] == "operation:openapi:get /pets"
    assert d["kind"] == "operation"
    assert d["domain"] == "openapi"
    assert d["identifier"] == "get /pets"
    assert d["file"] == "api.yaml"
    assert d["line"] == 7
    assert validate_named(d, "entity") == []


def test_entity_from_id_unknown_on_noncanonical() -> None:
    node = entity_from_id("not-an-entity-id")
    assert isinstance(node, UnknownFact)
    assert node.kind == "entity"
    assert "canonical" in node.reason


def test_wire_relationship_maps_and_carries_confidence() -> None:
    rel = wire_relationship(CoreRelationship(
        kind="CALLS",
        source_id="client:ext:sdk",
        target_id="operation:openapi:get /pets",
        confidence=Confidence.HIGH,
        evidence=(CoreEvidence(
            kind=EvidenceKind.STATIC, source="sdk.py",
            summary="client call"),),
    ))
    d = rel.to_dict()
    assert d["src"] == "client:ext:sdk"
    assert d["dst"] == "operation:openapi:get /pets"
    assert d["kind"] == "CALLS"
    assert d["evidence_kind"] == "static"
    assert d["attrs"]["confidence"] == "high"
    assert validate_named(d, "relationship") == []


def test_wire_unknown_maps_reason_and_detail() -> None:
    u = wire_unknown(CoreUnknown(
        subject="cap:IDEMPOTENT_OPERATION",
        missing="idempotency evidence",
        resolution="declare an Idempotency-Key header"))
    d = u.to_dict()
    assert d["subject"] == "cap:IDEMPOTENT_OPERATION"
    assert d["reason"] == "idempotency evidence"
    assert d["detail"] == "declare an Idempotency-Key header"
    assert d["kind"] == "evidence"
    assert validate_named(d, "unknown-fact") == []


def test_wire_capability_supported_with_refs() -> None:
    cap = wire_capability_gap(CapabilityGap(
        rule=DependencyRule.SAFE_RETRY,
        capability=CapabilityKind.RETRY,
        missing=CapabilityKind.IDEMPOTENT_OPERATION,
        detail="retry without idempotent evidence"))
    assert cap.status == "partial"
    assert validate_named(cap.to_dict(), "capability") == []

    detected = DetectedCapability(
        capability=CapabilityKind.MTLS,
        evidence=(CoreEvidence(
            kind=EvidenceKind.CONFIG, source="deploy.yaml",
            summary="mtls: true"),))
    wc = wire_capability(detected)
    assert wc.id == "MTLS"
    assert wc.domain == "api"
    assert wc.status == "supported"
    assert wc.evidence_refs == ("deploy.yaml",)
    assert validate_named(wc.to_dict(), "capability") == []


def test_wire_edge_export_carries_evidence_ids() -> None:
    rel = wire_edge_export(EdgeExport(
        from_id="a:b:c", to_id="a:b:d", kind="CALLS",
        evidence_ids=("ev:1",), confidence=Confidence.MEDIUM))
    d = rel.to_dict()
    assert d[API_EXTENSION]["evidence_ids"] == ["ev:1"]
    assert validate_named(d, "relationship") == []


# -- report-level adapters -------------------------------------------------------

def _report() -> DoctorReport:
    return DoctorReport(
        tool_version="0.1.0",
        project="demo",
        analysis_rev="rev123",
        findings=(
            _core_finding(),
            _core_finding(id="APISEC001", severity=Severity.CRITICAL),
        ),
        unknowns=(CoreUnknown(
            subject="cap:GRPC_CLIENT", missing="health evidence",
            resolution="enable grpc health service"),),
        graph_edges=(EdgeExport(
            from_id="client:ext:sdk", to_id="operation:openapi:get /pets",
            kind="CALLS", evidence_ids=("ev:9",),
            confidence=Confidence.HIGH),),
    )


def test_report_handoff_conforms() -> None:
    bundle = report_handoff(_report())
    payload = bundle.to_dict()
    assert validate_named(payload, "handoff") == []
    assert payload["tool"]["name"] == "forge-doctor-api"
    assert payload["contract_version"] == "forge-contracts/1"
    assert payload["summary"]["findings"] == 2
    assert payload[API_EXTENSION]["analysis_rev"] == "rev123"


def test_report_manifest_conforms() -> None:
    manifest = report_manifest(_report())
    payload = manifest.to_dict()
    assert validate_named(payload, "diagnostic-manifest") == []
    assert payload["finding_count"] == 2
    assert payload["unknown_count"] >= 1
    assert payload["domains"]


def test_report_handoff_round_trips_through_wire() -> None:
    payload = report_handoff(_report()).to_dict()
    decoded = HandoffBundle.from_dict(payload)
    assert decoded.tool == "forge-doctor-api"
    assert len(decoded.findings) == 2
    assert validate_named(decoded.to_dict(), "handoff") == []


def test_bounded_bundle_records_truncation() -> None:
    bundle = HandoffBundle(
        tool="forge-doctor-api",
        findings=tuple(WireFinding(
            check_id=f"OAS{i:03}", title="t", severity="info",
            category="oas", message="m") for i in range(5)),
        unknowns=(UnknownFact(
            subject="s", kind="k", reason="r"),))
    bounded = bundle.bounded(findings=2)
    assert len(bounded.findings) == 2
    trunc = [u for u in bounded.unknowns if u.kind == "truncated"]
    assert len(trunc) == 1
    assert "bounded to 2 of 5" in trunc[0].reason
    assert validate_named(bounded.to_dict(), "handoff") == []


# -- version negotiation ----------------------------------------------------------

def test_version_negotiation() -> None:
    assert negotiate("forge-contracts/1") == ContractVersion(
        "forge-contracts", 1)
    assert negotiate("forge-contracts/2") is None
    assert negotiate("other/1") is None
    assert within_range("forge-contracts/1")
    assert not within_range("forge-contracts/99")
    with pytest.raises(ValueError):
        ContractVersion.parse("no-slash")


# -- no cross-package import --------------------------------------------------------

def test_no_forge_doctor_data_import() -> None:
    """Spec 074 hard rule: the wire contract is shared, internals are not."""
    offenders: list[str] = []
    for base in (ROOT / "src", ROOT / "tests"):
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for n in names:
                    if n.split(".")[0] == "forge_doctor_data":
                        offenders.append(f"{path}: {n}")
    assert offenders == [], "forge_doctor_data imports: " + "; ".join(
        offenders)


def test_schemas_pinned_set() -> None:
    assert sorted(FORGE_CONTRACT_SCHEMAS) == [
        "capability", "diagnostic-manifest", "entity", "evidence",
        "finding", "handoff", "migration-plan", "relationship",
        "remediation-plan", "unknown-fact",
    ]
