from __future__ import annotations

import json
from typing import Any

import pytest

from forge_doctor_api import __version__
from forge_doctor_api.core.export import SCHEMA_VERSION, FindingsExport, export_findings
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    ModelError,
    Severity,
    SourceLocation,
    UnknownFact,
    check_namespace,
)

GAP = UnknownFact(
    subject="endpoint:http:GET:/payments/{id}",
    missing="gateway timeout configuration",
    resolution="provide the gateway policy export",
)


def make(**overrides: Any) -> Finding:
    values: dict[str, Any] = {
        "id": "OAS001",
        "title": "Missing operationId",
        "description": "GET /payments/{id} has no operationId",
        "severity": Severity.MEDIUM,
        "confidence": Confidence.HIGH,
        "evidence_kind": EvidenceKind.STATIC,
        "entity_ids": ("operation:openapi:getPayment",),
        "source_location": SourceLocation(path="api/openapi.yaml", line=12),
        "remediation": "add a unique operationId",
    }
    values.update(overrides)
    return Finding(**values)


# --- positive ---------------------------------------------------------------


def test_finding_carries_full_contract() -> None:
    finding = make(
        evidence=(Evidence(kind=EvidenceKind.STATIC, source="api/openapi.yaml", summary="s"),),
        unknowns=(GAP,),
    )
    assert set(finding.to_dict()) == {
        "id",
        "title",
        "description",
        "severity",
        "confidence",
        "evidence_kind",
        "evidence",
        "entity_ids",
        "source_location",
        "remediation",
        "unknowns",
    }
    assert finding.namespace == "OAS"


@pytest.mark.parametrize("kind", list(EvidenceKind))
def test_every_evidence_kind_accepted(kind: EvidenceKind) -> None:
    assert make(evidence_kind=kind).evidence_kind is kind


@pytest.mark.parametrize(
    ("check_id", "namespace"),
    [("OAS001", "OAS"), ("APISEC010", "APISEC"), ("GQL0001", "GQL"), ("RT999", "RT")],
)
def test_check_namespace_prefix(check_id: str, namespace: str) -> None:
    assert check_namespace(check_id) == namespace
    assert make(id=check_id).namespace == namespace


def test_unknown_is_first_class_state() -> None:
    finding = make(confidence=Confidence.UNKNOWN, unknowns=(GAP,))
    rebuilt = Finding.from_json(finding.to_json())
    assert rebuilt.confidence is Confidence.UNKNOWN
    assert rebuilt.unknowns == (GAP,)
    assert json.loads(finding.to_json())["unknowns"] == [
        {
            "missing": "gateway timeout configuration",
            "resolution": "provide the gateway policy export",
            "subject": "endpoint:http:GET:/payments/{id}",
        }
    ]


def test_optional_location_and_remediation() -> None:
    finding = make(source_location=None, remediation=None, evidence_kind=EvidenceKind.RUNTIME)
    data = finding.to_dict()
    assert data["source_location"] is None
    assert data["remediation"] is None
    assert Finding.from_dict(data) == finding


def test_export_carries_versions() -> None:
    payload = json.loads(export_findings([make()]).to_json())
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["tool_version"] == __version__
    assert len(payload["findings"]) == 1


def test_export_round_trip() -> None:
    unknown = make(id="OAS002", confidence=Confidence.UNKNOWN, unknowns=(GAP,))
    export = export_findings([make(), unknown])
    assert FindingsExport.from_json(export.to_json()) == export


def test_export_is_deterministic_regardless_of_input_order() -> None:
    findings = [
        make(id="OAS002"),
        make(id="OAS001", entity_ids=("operation:openapi:b",)),
        make(id="OAS001", entity_ids=("operation:openapi:a",)),
        make(id="APISEC001", evidence_kind=EvidenceKind.CONFIG),
    ]
    forward = export_findings(findings).to_json()
    backward = export_findings(reversed(findings)).to_json()
    assert forward.encode() == backward.encode()
    ids = [(f["id"], f["entity_ids"]) for f in json.loads(forward)["findings"]]
    assert ids == sorted(ids)


def test_empty_export_still_versioned() -> None:
    assert export_findings([]).to_json() == (
        f'{{"findings":[],"schema_version":"{SCHEMA_VERSION}","tool_version":"{__version__}"}}'
    )


# --- negative ---------------------------------------------------------------


def test_evidence_kind_is_required() -> None:
    data = make().to_dict()
    del data["evidence_kind"]
    with pytest.raises(ModelError, match="evidence_kind"):
        Finding.from_dict(data)
    with pytest.raises(TypeError, match="evidence_kind"):
        Finding(  # type: ignore[call-arg]
            id="OAS001",
            title="t",
            description="d",
            severity=Severity.LOW,
            confidence=Confidence.LOW,
        )


@pytest.mark.parametrize("bad", [None, "STATIC", "static", 1])
def test_evidence_kind_must_be_enum(bad: object) -> None:
    with pytest.raises(ModelError, match="evidence_kind"):
        make(evidence_kind=bad)


@pytest.mark.parametrize(
    ("field", "bad"), [("severity", "HIGH"), ("severity", None), ("confidence", "LOW")]
)
def test_severity_and_confidence_must_be_enums(field: str, bad: object) -> None:
    with pytest.raises(ModelError, match=field):
        make(**{field: bad})


def test_unknown_confidence_requires_unknowns() -> None:
    with pytest.raises(ModelError, match="UNKNOWN confidence"):
        make(confidence=Confidence.UNKNOWN)


@pytest.mark.parametrize(
    "check_id", ["", "oas001", "OAS1", "OAS00001", "O001", "OAS-001", "001OAS", "OAS001 ", None]
)
def test_invalid_check_ids_rejected(check_id: object) -> None:
    with pytest.raises(ModelError, match="check id"):
        make(id=check_id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": " "},
        {"description": ""},
        {"remediation": ""},
    ],
)
def test_blank_text_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ModelError):
        make(**overrides)


@pytest.mark.parametrize(
    "build",
    [
        lambda: SourceLocation(path=""),
        lambda: SourceLocation(path="src\\app.py"),
        lambda: SourceLocation(path="a.py", line=0),
        lambda: SourceLocation(path="a.py", column=3),
        lambda: SourceLocation(path="a.py", line=1, column=0),
        lambda: UnknownFact(subject="s", missing="", resolution="r"),
        lambda: FindingsExport(schema_version="1", tool_version="0.1.0"),
        lambda: FindingsExport(schema_version="1.0", tool_version=" "),
    ],
)
def test_invalid_supporting_models_rejected(build: object) -> None:
    with pytest.raises(ModelError):
        build()  # type: ignore[operator]


# --- malformed --------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(evidence_kind="GUESSED"),
        lambda d: d.update(evidence_kind=None),
        lambda d: d.update(severity="UNKNOWN"),
        lambda d: d.update(confidence="maybe"),
        lambda d: d.update(source_location="api/openapi.yaml:12"),
        lambda d: d.update(source_location={"path": "a.yaml", "line": "12"}),
        lambda d: d.update(unknowns=[{"subject": "s"}]),
        lambda d: d.update(remediation=7),
        lambda d: d.update(extra="field"),
        lambda d: d.update(id="not-a-check"),
    ],
)
def test_malformed_finding_payload_rejected(mutate: Any) -> None:
    data = make().to_dict()
    mutate(data)
    with pytest.raises(ModelError):
        Finding.from_dict(data)


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        "[]",
        '{"findings": []}',
        '{"schema_version": "1.0", "tool_version": "0.1.0", "findings": {}}',
        '{"schema_version": "v1", "tool_version": "0.1.0", "findings": []}',
        '{"schema_version": "1.0", "tool_version": "0.1.0", "findings": [{"id": "OAS001"}]}',
    ],
)
def test_malformed_export_rejected(payload: str) -> None:
    with pytest.raises(ModelError):
        FindingsExport.from_json(payload)
