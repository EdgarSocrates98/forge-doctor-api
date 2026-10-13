"""Spec 030 — §175/§176 output writer tests."""

from __future__ import annotations

import json

import forge_doctor_api
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.output.writers import (
    write_agent,
    write_json,
    write_jsonl,
    write_sarif,
)


def _finding(
    check_id: str = "OAS001",
    *,
    path: str | None = "openapi.yaml",
    line: int | None = 7,
    severity: Severity = Severity.HIGH,
    confidence: Confidence = Confidence.HIGH,
) -> Finding:
    return Finding(
        id=check_id,
        title=f"{check_id} title",
        description=f"{check_id} description",
        severity=severity,
        confidence=confidence,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=path or "model",
                line=line,
                summary="e",
            ),
        ),
        evidence_kind=EvidenceKind.STATIC,
        entity_ids=(f"operation:x:{check_id}",),
        source_location=(
            SourceLocation(path=path, line=line) if path is not None else None
        ),
    )


def test_json_envelope_metadata() -> None:
    doc = json.loads(write_json([_finding()]))
    assert doc["schema_version"] == "1.0"
    assert doc["tool_version"] == forge_doctor_api.__version__
    assert doc["knowledge_versions"]["openapi-versions"]
    assert len(doc["findings"]) == 1


def test_jsonl_first_line_is_metadata() -> None:
    lines = write_jsonl([_finding(), _finding("OAS002")]).strip().split("\n")
    assert len(lines) == 3
    meta = json.loads(lines[0])
    assert meta["_meta"] is True
    assert meta["tool_version"] == forge_doctor_api.__version__
    assert "knowledge_versions" in meta
    assert json.loads(lines[1])["id"] == "OAS001"


def test_sarif_structure() -> None:
    doc = json.loads(write_sarif([_finding(), _finding("APISEC003", line=None)]))
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-2.1.0.json")
    run = doc["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "forge-doctor-api"
    assert driver["version"] == forge_doctor_api.__version__
    rules = {r["id"] for r in driver["rules"]}
    assert rules == {"OAS001", "APISEC003"}
    assert len(run["results"]) == 2
    by_rule = {r["ruleId"]: r for r in run["results"]}
    result = by_rule["OAS001"]
    assert result["level"] == "error"  # HIGH severity maps to error
    loc = result["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "openapi.yaml"
    assert loc["region"]["startLine"] == 7
    # path-only location: no region object
    no_region = by_rule["APISEC003"]["locations"][0]["physicalLocation"]
    assert "region" not in no_region


def test_sarif_skips_locationless_results() -> None:
    """§176 — findings without a source location are counted, not faked."""
    doc = json.loads(write_sarif([_finding("OAS999", path=None)]))
    run = doc["runs"][0]
    assert run["results"] == []
    assert run["properties"]["skipped_no_location"] == 1
    # the rule is still declared so consumers can see what ran
    assert run["tool"]["driver"]["rules"][0]["id"] == "OAS999"


def test_sarif_level_mapping() -> None:
    cases = {
        Severity.CRITICAL: "error",
        Severity.HIGH: "error",
        Severity.MEDIUM: "warning",
        Severity.LOW: "note",
        Severity.INFO: "note",
    }
    for sev, level in cases.items():
        doc = json.loads(write_sarif([_finding(severity=sev)]))
        assert doc["runs"][0]["results"][0]["level"] == level, sev


def test_agent_compact_format() -> None:
    out = write_agent(
        [_finding()],
        [UnknownFact(subject="x", missing="m", resolution="r")],
    )
    lines = out.strip().split("\n")
    assert lines[0].startswith("# schema_version=")
    assert "tool_version=" in lines[0]
    assert "openapi-versions@" in lines[1]
    row = lines[2]
    assert row.startswith("OAS001|HIGH|HIGH|")
    assert "openapi.yaml:7" in row or ":7|" in row
    assert lines[3] == "UNKNOWN|x|m"


def test_writers_are_deterministic() -> None:
    findings = [_finding("OAS002"), _finding("OAS001")]
    assert write_json(findings) == write_json(findings)
    assert write_sarif(findings) == write_sarif(findings)
