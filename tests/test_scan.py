"""Spec 030 — §177 scan pipeline + §178 gate semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer.testing

from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.scan import (
    GateCategory,
    ScanReport,
    _GateConfigError,
    evaluate_gate,
    export_scan,
    scan_project,
)

runner = typer.testing.CliRunner()

_API = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /items:
    get:
      responses:
        "200": {description: ok}
"""

_API_V2 = """\
openapi: "3.0.3"
info: {title: T, version: "1.1"}
paths:
  /items:
    get:
      responses:
        "200": {description: ok}
  /gone:
    delete:
      operationId: gone
      responses:
        "200": {description: ok}
"""

_POLICY = """\
policies:
  - id: require-auth
    rule: require_auth
    applies_to: "/**"
"""


def _finding(
    check_id: str,
    confidence: Confidence = Confidence.HIGH,
    severity: Severity = Severity.HIGH,
) -> Finding:
    return Finding(
        id=check_id,
        title="t",
        description="d",
        severity=severity,
        confidence=confidence,
        evidence=(Evidence(kind=EvidenceKind.STATIC, source="f", summary="s"),),
        unknowns=(
            (UnknownFact(subject="s", missing="m", resolution="r"),)
            if confidence is Confidence.UNKNOWN else ()
        ),
        evidence_kind=EvidenceKind.STATIC,
        entity_ids=("e",),
        source_location=SourceLocation(path="f", line=1),
    )


def _project(root: Path, api: str = _API) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "openapi.yaml").write_text(api, encoding="utf-8")


# -- gate evaluation -------------------------------------------------------


def test_gate_security_needs_high_confidence() -> None:
    low = _finding("APISEC001", confidence=Confidence.LOW)
    assert evaluate_gate((low,), None, frozenset({GateCategory.SECURITY})) == ()
    high = _finding("APISEC001", confidence=Confidence.HIGH)
    failures = evaluate_gate((high,), None, frozenset({GateCategory.SECURITY}))
    assert len(failures) == 1
    assert failures[0].category is GateCategory.SECURITY


def test_gate_unknown_never_blocks() -> None:
    unknown = _finding("APISEC001", confidence=Confidence.UNKNOWN)
    unknown_low = _finding("APISEC009", confidence=Confidence.UNKNOWN)
    for categories in (
        frozenset({GateCategory.SECURITY}),
        frozenset({GateCategory.POLICY}),
        frozenset({GateCategory.SECURITY, GateCategory.POLICY}),
    ):
        assert evaluate_gate(
            (unknown, unknown_low), None, categories) == ()


def test_gate_policy_category() -> None:
    f = _finding("POLICY001", confidence=Confidence.HIGH)
    failures = evaluate_gate((f,), None, frozenset({GateCategory.POLICY}))
    assert failures and failures[0].category is GateCategory.POLICY


def test_gate_breaking_requires_baseline() -> None:
    with pytest.raises(_GateConfigError):
        evaluate_gate((), None, frozenset({GateCategory.BREAKING}))


def test_gate_breaking_on_diff(tmp_path: Path) -> None:
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    _project(old_dir, _API_V2)
    _project(new_dir, _API)
    report = scan_project(
        ProjectContext.from_root(new_dir),
        before=ProjectContext.from_root(old_dir),
    )
    assert report.diff is not None
    assert any(
        c.classification is CompatibilityClass.BREAKING
        for c in report.diff.changes
    )
    failures = evaluate_gate(
        report.findings, report.diff, frozenset({GateCategory.BREAKING}))
    assert failures and failures[0].category is GateCategory.BREAKING


def test_scan_project_runs_all_pipelines(tmp_path: Path) -> None:
    _project(tmp_path)
    report = scan_project(ProjectContext.from_root(tmp_path))
    ids = {f.id for f in report.findings}
    # OAS checks and security drift both ran on the same fixture
    assert "OAS004" in ids  # missing operationId
    assert report.gate_passed
    # deterministic ordering
    assert report.findings == tuple(sorted(
        report.findings,
        key=lambda f: (f.id, f.entity_ids, f.description)))


def test_export_scan_carries_metadata(tmp_path: Path) -> None:
    _project(tmp_path)
    payload = export_scan(scan_project(ProjectContext.from_root(tmp_path)))
    assert payload["schema_version"] == "1.0"
    assert payload["knowledge_versions"]["openapi-versions"]
    assert payload["gate_passed"] is True


# -- CLI -------------------------------------------------------------------


def test_scan_cli_exit_codes(tmp_path: Path) -> None:
    _project(tmp_path)
    ok = runner.invoke(app, ["scan", str(tmp_path)])
    assert ok.exit_code == 0, ok.stdout
    bad = runner.invoke(app, ["scan", str(tmp_path), "--fail-on", "bogus"])
    assert bad.exit_code == 2
    mis = runner.invoke(
        app, ["scan", str(tmp_path), "--fail-on", "breaking"])
    assert mis.exit_code == 2  # breaking gate needs a baseline


def test_scan_cli_fails_gate_on_breaking(tmp_path: Path) -> None:
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    _project(old_dir, _API_V2)
    _project(new_dir, _API)
    r = runner.invoke(app, [
        "scan", str(new_dir), "--fail-on", "breaking",
        "--baseline", str(old_dir)])
    assert r.exit_code == 1


def test_scan_cli_policy_option(tmp_path: Path) -> None:
    _project(tmp_path)
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    (policy_dir / "org.policy.yaml").write_text(_POLICY, encoding="utf-8")
    r = runner.invoke(app, [
        "scan", str(tmp_path), "--policy", str(policy_dir),
        "--fail-on", "policy"])
    assert r.exit_code == 1, r.stdout


def test_scan_cli_formats(tmp_path: Path) -> None:
    _project(tmp_path)
    for fmt in ("json", "jsonl", "sarif", "agent"):
        r = runner.invoke(
            app, ["scan", str(tmp_path), "--format", fmt])
        assert r.exit_code == 0, (fmt, r.stdout)
        assert r.stdout.strip(), fmt
    doc = json.loads(runner.invoke(
        app, ["scan", str(tmp_path), "--format", "sarif"]).stdout)
    assert doc["version"] == "2.1.0"


def test_scan_cli_out_file(tmp_path: Path) -> None:
    _project(tmp_path)
    out = tmp_path / "report.json"
    r = runner.invoke(
        app, ["scan", str(tmp_path), "--format", "json",
              "--out", str(out)])
    assert r.exit_code == 0
    assert json.loads(out.read_text())["tool_version"]


def test_scan_report_is_serializable(tmp_path: Path) -> None:
    _project(tmp_path)
    report = scan_project(ProjectContext.from_root(tmp_path))
    assert isinstance(report, ScanReport)
    json.dumps(report.to_dict())
