"""Spec 044 — public SDK: Doctor facade + curated import surface."""

from __future__ import annotations

from pathlib import Path

import pytest

import forge_doctor_api
from forge_doctor_api import (
    Doctor,
    DoctorReport,
    FindingNotFoundError,
    ProjectUnreadableError,
)
from forge_doctor_api.sdk import SDK_VERSION

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

EXPECTED_ALL = sorted([
    "SDK_VERSION",
    "AnalysisPlan",
    "ApiHandoffBundle",
    "ArtifactInventory",
    "Confidence",
    "Doctor",
    "DoctorError",
    "DoctorReport",
    "DomainSummary",
    "Evidence",
    "EvidenceKind",
    "Finding",
    "FindingNotFoundError",
    "ForgeHandoff",
    "ForgeReceipt",
    "ForgeRef",
    "ForgeRequest",
    "ForgeResult",
    "Model",
    "ProjectContext",
    "ProjectUnreadableError",
    "Severity",
    "SourceLocation",
    "UnknownFact",
    "__version__",
    "assemble_bundle",
])


def _project(tmp_path: Path) -> Path:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return tmp_path


def test_import_surface_snapshot() -> None:
    assert sorted(forge_doctor_api.__all__) == EXPECTED_ALL


def test_from_path_errors_are_typed(tmp_path: Path) -> None:
    with pytest.raises(ProjectUnreadableError):
        Doctor.from_path(tmp_path / "nope")
    with pytest.raises(ProjectUnreadableError):
        Doctor.from_path(tmp_path / "file.txt") if (
            tmp_path / "file.txt").write_text("x") else None


def test_scan_round_trip(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    report = doctor.scan()
    assert isinstance(report, DoctorReport)
    assert report.contracts is not None
    assert report.schema_version


def test_inventory_and_capabilities(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    inv = doctor.inventory()
    assert inv.counts_by_class().get("contract", 0) >= 1
    caps = doctor.capabilities()
    assert isinstance(caps, tuple)


def test_handoff_v2(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    bundle = doctor.handoff()
    assert bundle.handoff_version == 2
    assert len(bundle.handoff_id) == 64


def test_explain_found_and_missing(tmp_path: Path) -> None:
    doctor = Doctor.from_path(_project(tmp_path))
    report = doctor.scan()
    if report.findings:
        f = report.findings[0]
        ex = doctor.explain(f.id)
        assert ex.finding.id == f.id
        assert ex.why
    with pytest.raises(FindingNotFoundError):
        doctor.explain("NOPE-999")


def test_determinism(tmp_path: Path) -> None:
    d1 = Doctor.from_path(_project(tmp_path)).scan().to_json()
    d2 = Doctor.from_path(_project(tmp_path)).scan().to_json()
    assert d1 == d2


def test_sdk_version_matches_package() -> None:
    assert forge_doctor_api.__version__ == SDK_VERSION
