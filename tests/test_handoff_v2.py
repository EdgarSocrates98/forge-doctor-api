"""Spec 047 — Handoff V2: deterministic id, content hashes, receipt."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.handoff.bundle import (
    assemble_bundle,
    assemble_bundle_v2,
    build_handoff,
)
from forge_doctor_api.handoff.protocol import build_receipt
from forge_doctor_api.scan import scan_project

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""


def _report(tmp_path: Path):
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return scan_project(ProjectContext.from_root(tmp_path))


def test_v1_unchanged_shape(tmp_path: Path) -> None:
    report = _report(tmp_path)
    bundle = assemble_bundle(findings=report.findings)
    assert bundle.handoff_version == 1
    assert bundle.handoff_id == ""
    assert bundle.analysis_rev is None
    assert bundle.domain_sha256 == ()
    assert bundle.context_refs == ()


def test_v2_deterministic_id(tmp_path: Path) -> None:
    r1 = _report(tmp_path)
    r2 = _report(tmp_path)
    b1 = assemble_bundle_v2(r1, findings=r1.findings,
                            unknowns=r1.unknowns)
    b2 = assemble_bundle_v2(r2, findings=r2.findings,
                            unknowns=r2.unknowns)
    assert b1.handoff_version == 2
    assert b1.handoff_id == b2.handoff_id  # content-addressed
    assert len(b1.handoff_id) == 64
    assert b1.analysis_rev == r1.analysis_rev


def test_v2_domain_hashes_and_refs(tmp_path: Path) -> None:
    report = _report(tmp_path)
    bundle = assemble_bundle_v2(report, findings=report.findings)
    names = dict(bundle.domain_sha256)
    assert "contracts" in names  # openapi fixture
    assert "runtime" not in names  # absent domain, no hash
    assert any(r.startswith("doctor://service") for r in bundle.context_refs)


def test_v2_requires_report(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="requires the source"):
        assemble_bundle(handoff_version=2)


def test_build_handoff_and_receipt(tmp_path: Path) -> None:
    report = _report(tmp_path)
    bundle = assemble_bundle_v2(report, findings=report.findings)
    handoff = build_handoff(report, bundle)
    assert handoff.handoff_id == bundle.handoff_id
    assert handoff.analysis_rev == report.analysis_rev
    assert handoff.bundle_ref.startswith("doctor://handoff/")
    receipt = build_receipt(handoff, "api-forge")
    assert receipt.analysis_rev == report.analysis_rev
    assert receipt.handoff_id == bundle.handoff_id


def test_v1_v2_shared_fields(tmp_path: Path) -> None:
    report = _report(tmp_path)
    v1 = assemble_bundle(findings=report.findings,
                         unknowns=report.unknowns)
    v2 = assemble_bundle_v2(report, findings=report.findings,
                            unknowns=report.unknowns)
    assert v1.findings == v2.findings
    assert v1.unknowns == v2.unknowns
    assert v1.operations == v2.operations
