"""DoctorReport (spec 039) — unified compact report contract.

Covers: empty project, domain presence/absence, deterministic
serialization, redaction (no schema bodies / spans / payloads), and
artifact counts by class.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.report import DOCTOR_REPORT_SCHEMA_VERSION
from forge_doctor_api.scan import scan_project

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties:
                  secretField: {type: string}
"""

DOMAIN_FIELDS = (
    "contracts", "routes", "clients", "graph", "gateway", "mesh",
    "infrastructure", "cache", "runtime", "security", "reliability",
    "policies", "twin", "fanout", "migration", "impact",
)


def _scan(root: Path, files: dict[str, str]):
    for name, text in files.items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return scan_project(ProjectContext.from_root(root))


def test_empty_project_all_domains_none(tmp_path: Path) -> None:
    report = _scan(tmp_path, {})
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == DOCTOR_REPORT_SCHEMA_VERSION
    assert report.findings == ()
    for field in DOMAIN_FIELDS:
        assert payload.get(field) is None, field


def test_openapi_only_domains(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"api.yaml": OPENAPI})
    payload = json.loads(report.to_json())
    assert payload["contracts"] is not None
    assert payload["runtime"] is None
    assert payload["gateway"] is None
    assert payload["infrastructure"] is None
    assert payload["cache"] is None
    # security/reliability models always load (contract evidence present)
    counts = dict(payload["contracts"]["counts"])
    assert counts["documents"] == 1


def test_report_is_byte_stable(tmp_path: Path) -> None:
    files = {"api.yaml": OPENAPI, "notes.md": "# readme\n"}
    a = _scan(tmp_path / "a" if False else tmp_path, files)
    first = a.to_json()
    second = _scan(tmp_path, files).to_json()
    assert first == second


def test_report_has_no_payloads(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"api.yaml": OPENAPI})
    blob = report.to_json()
    # schema bodies and property names must never serialize
    assert "secretField" not in blob
    assert '"spans"' not in blob
    # counts/ids only
    assert "listPets" in blob or "GET /pets" in blob


def test_artifact_counts_by_class(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"api.yaml": OPENAPI})
    counts = report.artifact_counts()
    assert counts.get("contract", 0) >= 1


def test_analysis_rev_is_content_hash(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"api.yaml": OPENAPI})
    assert report.analysis_rev is not None
    assert len(report.analysis_rev) == 64


def test_plan_and_inventory_present(tmp_path: Path) -> None:
    report = _scan(tmp_path, {"api.yaml": OPENAPI})
    assert report.plan is not None
    assert report.inventory is not None
    analyzers = [a.value if hasattr(a, "value") else str(a)
                 for a in report.plan.analyzers]
    # registry order is deterministic, not alphabetical
    again = _scan(tmp_path, {"api.yaml": OPENAPI})
    assert analyzers == [
        a.value if hasattr(a, "value") else str(a)
        for a in again.plan.analyzers]
