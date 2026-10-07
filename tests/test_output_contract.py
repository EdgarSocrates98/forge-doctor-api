"""Spec 067 — output contract: structural tests over every writer.

Each exported surface (json, jsonl, sarif, agent, report) has a
frozen v1 shape documented in `docs/output-contract.md`. These tests
assert the shapes mechanically — including validating SARIF output
against the committed `tests/schemas/sarif-2.1.0-schema.json` subset
with a small dependency-free validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
)
from forge_doctor_api.output.writers import (
    write_agent,
    write_json,
    write_jsonl,
    write_sarif,
)
from forge_doctor_api.scan import scan_project

SCHEMA = json.loads(
    (Path(__file__).parent / "schemas" / "sarif-2.1.0-schema.json")
    .read_text(encoding="utf-8"))

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""


def _finding(**kw: Any) -> Finding:
    base: dict[str, Any] = {
        "id": "OAS099",
        "title": "t",
        "description": "d",
        "severity": Severity.HIGH,
        "confidence": Confidence.HIGH,
        "evidence_kind": EvidenceKind.STATIC,
    }
    base.update(kw)
    return Finding(**base)


# -- minimal JSON-schema-subset validator ------------------------------------
# supports: type, required, properties, items, enum, const, minItems, minimum

_TYPE_MAP = {
    "object": dict, "array": list, "string": str,
    "integer": int, "boolean": bool, "number": (int, float),
}


def _validate(instance: Any, schema: dict[str, Any], path: str = "$"
              ) -> list[str]:
    errors: list[str] = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum")
    if "type" in schema:
        tp = schema["type"]
        py = _TYPE_MAP[tp]
        if tp in ("integer", "number") and isinstance(instance, bool):
            errors.append(f"{path}: bool is not {tp}")
        elif not isinstance(instance, py):
            errors.append(f"{path}: expected {tp}, got "
                          f"{type(instance).__name__}")
            return errors
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(
                    _validate(instance[key], sub, f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        for i, item in enumerate(instance):
            if "items" in schema:
                errors.extend(
                    _validate(item, schema["items"], f"{path}[{i}]"))
    if ("minimum" in schema and isinstance(instance, int | float)
            and not isinstance(instance, bool)
            and instance < schema["minimum"]):
        errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
    return errors


# -- json --------------------------------------------------------------------

def test_json_envelope_contract() -> None:
    doc = json.loads(write_json([_finding()]))
    assert set(doc) == {
        "schema_version", "tool_version",
        "knowledge_versions", "findings"}
    assert isinstance(doc["schema_version"], str)
    assert isinstance(doc["knowledge_versions"], dict)
    f = doc["findings"][0]
    for field in ("id", "title", "description", "severity",
                  "confidence", "evidence_kind", "evidence",
                  "entity_ids", "unknowns"):
        assert field in f, field


def test_jsonl_contract() -> None:
    out = write_jsonl([_finding(), _finding(id="OAS098")])
    lines = out.splitlines()
    assert out.endswith("\n")
    meta = json.loads(lines[0])
    assert meta["_meta"] is True
    assert "schema_version" in meta and "tool_version" in meta
    assert len(lines) == 3
    for line in lines[1:]:
        assert json.loads(line)["id"].startswith("OAS0")


# -- sarif -------------------------------------------------------------------

def _sarif_doc() -> dict[str, Any]:
    findings = [
        _finding(source_location=SourceLocation(path="api.yaml", line=3)),
        _finding(id="OAS098"),  # no location → skipped from results
    ]
    return json.loads(write_sarif(findings))


def test_sarif_validates_against_committed_schema() -> None:
    errors = _validate(_sarif_doc(), SCHEMA)
    assert errors == [], "\n".join(errors)


def test_sarif_skipped_no_location_never_faked() -> None:
    doc = _sarif_doc()
    run = doc["runs"][0]
    assert run["properties"]["skipped_no_location"] == 1
    assert len(run["results"]) == 1
    assert len(run["tool"]["driver"]["rules"]) == 2  # rule still listed


def test_sarif_is_valid_210() -> None:
    doc = _sarif_doc()
    assert doc["version"] == "2.1.0"
    assert "$schema" in doc


# -- agent -------------------------------------------------------------------

def test_agent_contract_and_bounded_size() -> None:
    findings = [_finding(id=f"OAS0{i:02d}") for i in range(90, 50, -1)]
    unknowns: list[Any] = []
    out = write_agent(findings, unknowns)
    lines = out.splitlines()
    assert lines[0].startswith("# schema_version=")
    assert lines[1].startswith("# knowledge_versions=")
    # exactly one line per finding — bounded, no wrapping
    assert len(lines) == 2 + len(findings)
    for line in lines[2:]:
        parts = line.split("|")
        assert len(parts) == 5
        assert "\n" not in line and "\r" not in line
        assert parts[0].startswith("OAS0")


# -- report ------------------------------------------------------------------

def test_report_contract_surface(tmp_path: Path) -> None:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    report = scan_project(ProjectContext.from_root(tmp_path))
    payload = json.loads(report.to_json())
    for field in ("schema_version", "tool_version",
                  "knowledge_versions", "project", "inventory", "plan",
                  "analysis_rev", "stats", "findings", "unknowns",
                  "capabilities"):
        assert field in payload, field
    # stats fields are the frozen analyzer-stat shape
    for a in payload["stats"]["analyzers"]:
        assert set(a) >= {"analyzer", "ran", "artifacts",
                          "findings", "unknowns"}
    # no duration without the opt-in flag
    assert all(a.get("duration_ms") is None
               for a in payload["stats"]["analyzers"])


def test_report_v1_frozen_shape(tmp_path: Path) -> None:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    report = scan_project(ProjectContext.from_root(tmp_path))
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == "1.0"
    assert isinstance(payload["analysis_rev"], str)
    assert len(payload["analysis_rev"]) == 64
