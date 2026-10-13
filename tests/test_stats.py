"""Spec 066 — analysis stats + explain surfaces.

Covers: per-analyzer counters match execution, totals match the
report, timing is opt-in and never enters canonical output, and
explain carries rule description + evidence + unknowns + next-evidence
suggestions via SDK/CLI/MCP-shaped payloads.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.stats import describe_check
from forge_doctor_api.scan import scan_project
from forge_doctor_api.sdk import Doctor

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
                  name: {type: string}
"""


def _project(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    for name, text in (files or {"api.yaml": OPENAPI}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_stats_present_and_totals_match(tmp_path: Path) -> None:
    report = scan_project(
        ProjectContext.from_root(_project(tmp_path)))
    stats = report.stats
    assert stats is not None
    assert stats.total_findings == len(report.findings)
    assert stats.total_unknowns == len(report.unknowns)
    emitted_f = sum(a.findings for a in stats.analyzers)
    emitted_u = sum(a.unknowns for a in stats.analyzers)
    # per-analyzer deltas must account for every emitted item
    assert emitted_f == stats.total_findings
    assert emitted_u == stats.total_unknowns


def test_stats_analyzer_rows(tmp_path: Path) -> None:
    report = scan_project(
        ProjectContext.from_root(_project(tmp_path)))
    by_name = {a.analyzer: a for a in report.stats.analyzers}
    openapi = by_name["openapi"]
    assert openapi.ran is True
    assert openapi.artifacts == 1
    # never-ran analyzers are still reported when the plan enables them
    assert all(a.findings >= 0 and a.unknowns >= 0
               for a in report.stats.analyzers)


def test_stats_timing_opt_in_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    quiet = scan_project(
        ProjectContext.from_root(root), stats_timing=False)
    timed = scan_project(
        ProjectContext.from_root(root), stats_timing=True)
    assert all(a.duration_ms is None for a in quiet.stats.analyzers)
    assert any(a.duration_ms is not None for a in timed.stats.analyzers)


def test_timing_never_enters_deterministic_output(tmp_path: Path) -> None:
    root = _project(tmp_path)
    a = scan_project(ProjectContext.from_root(root)).to_json()
    b = scan_project(ProjectContext.from_root(root)).to_json()
    assert a == b
    assert "duration_ms" not in a or '"duration_ms":null' in a.replace(
        " ", "")


def test_stats_in_json_payload(tmp_path: Path) -> None:
    report = scan_project(
        ProjectContext.from_root(_project(tmp_path)))
    payload = json.loads(report.to_json())
    assert payload["stats"]["total_findings"] == len(report.findings)
    names = {a["analyzer"] for a in payload["stats"]["analyzers"]}
    assert "openapi" in names


def test_describe_check_catalog_lookup() -> None:
    from forge_doctor_api.core.stats import rule_dict, rule_text

    spec = describe_check("OAS001")
    assert spec is not None
    assert spec.title and rule_text(spec)
    d = rule_dict(spec)
    assert d["severity"] and d["description"]
    assert describe_check("NOPE-999") is None


def test_explain_known_finding(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    report = doctor.scan()
    assert report.findings
    f = report.findings[0]
    ex = doctor.explain(f.id)
    assert ex.finding.id == f.id
    assert ex.rule is not None
    assert ex.rule.description
    assert ex.evidence
    assert ex.why


def test_explain_unknown_finding(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    report = doctor.scan()
    unknown_findings = [f for f in report.findings if f.unknowns]
    assert unknown_findings, "fixture must emit an unknown finding"
    f = unknown_findings[0]
    ex = doctor.explain(f.id)
    assert ex.unknowns
    assert ex.next_evidence
    assert all(u.resolution for u in ex.unknowns)
    d = ex.to_dict()
    assert d["next_evidence"]
    assert d["rule"] is None or d["rule"]["description"]


def test_explain_cli(tmp_path: Path) -> None:
    root = _project(tmp_path)
    report = scan_project(ProjectContext.from_root(root))
    f = report.findings[0]
    runner = CliRunner()
    res = runner.invoke(app, ["explain", str(root), f.id])
    assert res.exit_code == 0, res.output
    assert f.id in res.output
    assert "rule:" in res.output or "evidence kind" in res.output
    res_json = runner.invoke(app, ["explain", str(root), f.id, "--json"])
    assert res_json.exit_code == 0
    assert json.loads(res_json.output)["id"] == f.id


def test_explain_cli_not_found(tmp_path: Path) -> None:
    root = _project(tmp_path)
    res = CliRunner().invoke(app, ["explain", str(root), "NOPE-999"])
    assert res.exit_code == 2
