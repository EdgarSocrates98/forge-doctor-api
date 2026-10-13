"""Spec 082 — cross-doctor conformance, final form.

Pins the wire contract's invariants so any conforming implementation
(Python or not) agrees on them:

- canonical per-model fixtures decode and re-emit byte-identically
  (after key ordering) and validate against the published schemas;
- null semantics: required-scalar missing *and* explicit null are
  errors; collections decode missing/null/[] to empty; optional
  scalars decode missing/null to ``None`` and are omitted on output;
- forward compatibility: ``x-*`` keys survive round trips, strict
  protocol parsers reject unknown non-``x-*`` fields, and extensions
  never change universal semantics;
- API-specific data lives only under ``x-forge-api`` — the emitted
  key set equals the registered key set (docs/x-forge-api.md);
- DeltaContext carries its delta categories on the wire;
- no orchestration fields exist anywhere in the universal payloads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from forge_doctor_api.contracts import (
    API_EXTENSION,
    Capability,
    ContractError,
    DiagnosticManifest,
    Entity,
    Evidence,
    Finding,
    HandoffBundle,
    MigrationPlan,
    Relationship,
    RemediationPlan,
    UnknownFact,
    report_handoff,
    report_manifest,
    validate_named,
)
from forge_doctor_api.contracts.models import ContractModel
from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
)
from forge_doctor_api.core.models import Evidence as CoreEvidence
from forge_doctor_api.core.models import Finding as CoreFinding
from forge_doctor_api.core.models import (
    UnknownFact as CoreUnknown,
)
from forge_doctor_api.handoff.delta import compute_delta
from forge_doctor_api.handoff.protocol import (
    ForgeRequest,
    ProtocolError,
)
from forge_doctor_api.report import DoctorReport

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "tests" / "fixtures" / "contracts" / "canonical"
REGISTRY_DOC = ROOT / "docs" / "x-forge-api.md"

MODEL_BY_FIXTURE: dict[str, type[ContractModel]] = {
    "entity": Entity,
    "relationship": Relationship,
    "evidence": Evidence,
    "finding": Finding,
    "capability": Capability,
    "unknown-fact": UnknownFact,
    "migration-plan": MigrationPlan,
    "remediation-plan": RemediationPlan,
    "handoff": HandoffBundle,
    "diagnostic-manifest": DiagnosticManifest,
}


def _fixture(name: str) -> dict[str, Any]:
    return json.loads(
        (CANONICAL / f"{name}.json").read_text(encoding="utf-8"))


# -- canonical fixture round trips ----------------------------------------------

@pytest.mark.parametrize("name", sorted(MODEL_BY_FIXTURE))
def test_canonical_fixture_round_trips_byte_identical(name: str) -> None:
    payload = _fixture(name)
    model = MODEL_BY_FIXTURE[name].from_dict(payload)  # type: ignore[attr-defined]
    assert model.to_dict() == payload, (
        f"{name}: from_dict(to_dict) changed the wire shape")


@pytest.mark.parametrize("name", sorted(MODEL_BY_FIXTURE))
def test_canonical_fixture_validates_against_schema(name: str) -> None:
    assert validate_named(_fixture(name), name) == []


@pytest.mark.parametrize("name", sorted(MODEL_BY_FIXTURE))
def test_canonical_fixture_extension_survives(name: str) -> None:
    """Every canonical fixture carries an x-* key; it must round-trip."""
    payload = _fixture(name)
    ext_keys = {k for k in payload if k.startswith("x-")}
    assert ext_keys, f"{name} fixture must exercise an extension key"
    model = MODEL_BY_FIXTURE[name].from_dict(payload)  # type: ignore[attr-defined]
    out = model.to_dict()
    for key in ext_keys:
        assert out[key] == payload[key]


def test_canonical_fixture_set_is_complete() -> None:
    """Every schema name has a canonical fixture and vice versa."""
    on_disk = {p.stem for p in CANONICAL.glob("*.json")}
    assert on_disk == set(MODEL_BY_FIXTURE)


# -- null / empty semantics -------------------------------------------------------

def _minimal(model: type[ContractModel]) -> dict[str, Any]:
    return json.loads(model().to_json())


@pytest.mark.parametrize("field", [
    "check_id", "title", "severity", "category", "message"])
def test_finding_required_field_missing_or_null_errors(field: str) -> None:
    base = _fixture("finding")
    for bad in ({k: v for k, v in base.items() if k != field},
                {**base, field: None}):
        with pytest.raises((ValueError, ContractError)):
            Finding.from_dict(bad)


@pytest.mark.parametrize("model,field", [
    (Entity, "id"), (Entity, "kind"), (Entity, "domain"),
    (Relationship, "src"), (Relationship, "dst"), (Relationship, "kind"),
    (Evidence, "ref"), (Evidence, "kind"), (Evidence, "source"),
    (Capability, "id"), (Capability, "domain"), (Capability, "status"),
    (UnknownFact, "subject"), (UnknownFact, "kind"), (UnknownFact, "reason"),
    (MigrationPlan, "id"), (MigrationPlan, "source"),
    (MigrationPlan, "target"), (MigrationPlan, "kind"),
    (RemediationPlan, "id"), (RemediationPlan, "check_id"),
    (RemediationPlan, "problem"),
])
def test_required_scalar_missing_and_null_error(
        model: type[ContractModel], field: str) -> None:
    base = _minimal(model)
    assert field in base, f"{model.__name__} must emit {field}"
    for bad in ({k: v for k, v in base.items() if k != field},
                {**base, field: None}):
        with pytest.raises((ValueError, ContractError)):
            model.from_dict(bad)  # type: ignore[attr-defined]


@pytest.mark.parametrize("model,field", [
    (Finding, "tags"),
    (Capability, "evidence_refs"),
    (MigrationPlan, "steps"), (MigrationPlan, "risks"),
    (RemediationPlan, "targets"), (RemediationPlan, "actions"),
    (RemediationPlan, "risks"),
    (HandoffBundle, "findings"), (HandoffBundle, "entities"),
    (HandoffBundle, "relationships"), (HandoffBundle, "capabilities"),
    (HandoffBundle, "plans"), (HandoffBundle, "unknowns"),
])
def test_collection_missing_null_empty_decode_to_empty(
        model: type[ContractModel], field: str) -> None:
    for variant in ({}, {field: None}, {field: []}):
        base = {**_minimal(model), **variant}
        decoded = model.from_dict(base)  # type: ignore[attr-defined]
        assert getattr(decoded, field) == ()


@pytest.mark.parametrize("model,field,attr", [
    (Finding, "file", "file"),
    (Finding, "confidence", "confidence"),
    (Entity, "file", "file"),
    (Relationship, "evidence_kind", "evidence_kind"),
    (Evidence, "detail", "detail"),
    (Capability, "confidence", "confidence"),
    (UnknownFact, "source", "source"),
    (MigrationPlan, "readiness", "readiness"),
])
def test_optional_scalar_absent_null_decodes_none_and_omits(
        model: type[ContractModel], field: str, attr: str) -> None:
    for variant in ({}, {field: None}):
        base = {**_minimal(model), **variant}
        decoded = model.from_dict(base)  # type: ignore[attr-defined]
        assert getattr(decoded, attr) is None
        assert attr not in decoded.to_dict(), (
            f"{model.__name__}.{attr} must be omitted when null")


# -- forward compatibility ---------------------------------------------------------

def test_unknown_x_key_survives_round_trip() -> None:
    payload = {**_fixture("finding"), "x-future-v2": {"nested": [1, 2]}}
    out = Finding.from_dict(payload).to_dict()
    assert out["x-future-v2"] == {"nested": [1, 2]}


def test_unknown_x_key_survives_on_bundle() -> None:
    payload = {**_fixture("handoff"), "x-tenant": {"id": "acme"}}
    out = HandoffBundle.from_dict(payload).to_dict()
    assert out["x-tenant"] == {"id": "acme"}


def test_strict_protocol_parsers_reject_unknown_non_x_fields() -> None:
    with pytest.raises(ProtocolError):
        ForgeRequest.parse({"target": "p", "bogus": 1})
    ok = ForgeRequest.parse({"target": "p", "x-forward": {"a": 1}})
    assert ok.target == "p"


def test_extensions_do_not_change_universal_semantics() -> None:
    base = _fixture("finding")
    stripped = {k: v for k, v in base.items() if not k.startswith("x-")}
    with_ext = Finding.from_dict(base)
    without_ext = Finding.from_dict(stripped)
    for field in ("check_id", "title", "severity", "category",
                  "message", "file", "line", "confidence", "evidence"):
        assert getattr(with_ext, field) == getattr(without_ext, field)


# -- x-forge-api registry ----------------------------------------------------------

def _core_finding_with_unknowns() -> CoreFinding:
    return CoreFinding(
        id="OAS009", title="t", description="d",
        severity=Severity.MEDIUM, confidence=Confidence.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        evidence=(CoreEvidence(
            kind=EvidenceKind.STATIC, source="api.yaml",
            summary="s", line=1),),
        entity_ids=("operation:openapi:get /pets",),
        unknowns=(CoreUnknown(
            subject="s", missing="m", resolution="r"),),
    )


def _emitted_extension_keys() -> set[str]:
    """Every x-forge-api key the adapters can emit, exercised live."""
    from forge_doctor_api.contracts.adapters import (
        wire_edge_export,
        wire_finding,
        wire_relationship,
    )
    from forge_doctor_api.core.graph import EdgeExport
    from forge_doctor_api.core.models import (
        Relationship as CoreRelationship,
    )
    keys: set[str] = set()
    f = wire_finding(_core_finding_with_unknowns())
    keys |= set(f.extensions.get(API_EXTENSION, {}))
    rel = wire_relationship(CoreRelationship(
        source_id="a:b:c", target_id="a:b:d", kind="EXPOSES",
        confidence=Confidence.HIGH,
        evidence=(CoreEvidence(
            kind=EvidenceKind.STATIC, source="api.yaml",
            summary="edge"),),
        unknowns=(CoreUnknown(
            subject="s", missing="m", resolution="r"),)))
    keys |= set(rel.extensions.get(API_EXTENSION, {}))
    edge = wire_edge_export(EdgeExport(
        from_id="a:b:c", to_id="a:b:d", kind="CALLS",
        evidence_ids=("ev:1",), confidence=Confidence.HIGH))
    keys |= set(edge.extensions.get(API_EXTENSION, {}))
    report = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev1",
        findings=(_core_finding_with_unknowns(),))
    keys |= set(report_handoff(report).extensions.get(
        API_EXTENSION, {}))
    keys |= set(report_manifest(report).extensions.get(
        API_EXTENSION, {}))
    return keys


def _registered_extension_keys() -> set[str]:
    doc = REGISTRY_DOC.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", doc, re.DOTALL)
    assert match, "docs/x-forge-api.md must embed a json registry block"
    registry = json.loads(match.group(1))
    return set(registry["keys"])


def test_x_forge_api_registry_matches_emitted_keys() -> None:
    emitted = _emitted_extension_keys()
    registered = _registered_extension_keys()
    assert emitted == registered, (
        f"emitted-not-registered: {sorted(emitted - registered)}; "
        f"registered-not-emitted: {sorted(registered - emitted)}")


def test_no_api_specific_root_fields_outside_extension() -> None:
    """The bundle root carries only universal keys + x-* extensions."""
    report = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev1",
        findings=(_core_finding_with_unknowns(),))
    payload = report_handoff(report).to_dict()
    allowed = {
        "contract_version", "tool", "project", "summary", "findings",
        "entities", "relationships", "capabilities", "plans",
        "unknowns",
    }
    extras = set(payload) - allowed
    assert all(k.startswith("x-") for k in extras), (
        f"non-extension root keys leaked: {sorted(extras)}")


# -- delta context categories -------------------------------------------------------

def _report(rev: str, findings: tuple[CoreFinding, ...] = (),
            ) -> DoctorReport:
    return DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev=rev,
        findings=findings)


def test_delta_context_categories() -> None:
    prev = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev-a",
        findings=(_core_finding_with_unknowns(),),
        unknowns=(CoreUnknown(
            subject="cap:GRPC", missing="proto files",
            resolution="add .proto sources"),))
    cur = _report("rev-b")
    delta = compute_delta(
        prev, cur, baseline_ref="doctor://handoff/rev-a",
        changed_files=("b.py", "a.py"))
    assert delta.changed_files == ("a.py", "b.py")  # sorted echo
    assert delta.baseline_ref == "doctor://handoff/rev-a"
    assert delta.analysis_rev_prev == "rev-a"
    assert delta.analysis_rev_cur == "rev-b"
    assert delta.findings_removed == ("OAS009|operation:openapi:get /pets",)
    assert delta.unknowns_removed  # report-level unknown carried
    assert delta.protocol_diff == ()


def test_delta_context_capability_and_domain_transitions() -> None:
    from forge_doctor_api.knowledge.capability import (
        Capability as CapabilityKind,
    )
    from forge_doctor_api.knowledge.capability import (
        DetectedCapability,
    )
    cap = DetectedCapability(
        capability=CapabilityKind.OPENAPI_32,
        evidence=(CoreEvidence(
            kind=EvidenceKind.STATIC, source="api.yaml",
            summary="openapi: 3"),))
    prev = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev-a",
        capabilities=(cap,))
    cur = _report("rev-b")
    delta = compute_delta(prev, cur)
    assert "-capability:OPENAPI_32" in delta.protocol_diff
    assert delta.capabilities_removed == ("OPENAPI_32",)


def test_delta_context_initial_run() -> None:
    from forge_doctor_api.knowledge.capability import (
        Capability as CapabilityKind,
    )
    from forge_doctor_api.knowledge.capability import (
        DetectedCapability,
    )
    cap = DetectedCapability(
        capability=CapabilityKind.OPENAPI_32,
        evidence=(CoreEvidence(
            kind=EvidenceKind.STATIC, source="api.yaml",
            summary="openapi: 3"),))
    cur = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev-a",
        capabilities=(cap,))
    delta = compute_delta(None, cur)
    assert delta.initial is True
    assert delta.analysis_rev_cur == "rev-a"
    assert "+capability:OPENAPI_32" in delta.protocol_diff


# -- no orchestration fields ---------------------------------------------------------

def _walk_keys(node: Any, out: set[str]) -> set[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k))
            _walk_keys(v, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _walk_keys(item, out)
    return out


def test_no_orchestration_fields_in_universal_payloads() -> None:
    """The Doctor hands over facts — never routing/scheduling keys."""
    banned = {"next_tool", "route_to", "schedule", "delegate",
              "invoke"}
    report = DoctorReport(
        tool_version="0.1.0", project="demo", analysis_rev="rev1",
        findings=(_core_finding_with_unknowns(),))
    payloads = [
        report_handoff(report).to_dict(),
        report_manifest(report).to_dict(),
        *[_fixture(n) for n in MODEL_BY_FIXTURE],
    ]
    for payload in payloads:
        leaked = _walk_keys(payload, set()) & banned
        assert not leaked, f"orchestration fields leaked: {leaked}"
