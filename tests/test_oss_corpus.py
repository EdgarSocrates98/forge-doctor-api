"""Spec 077 — real-world OSS corpus: provenance + honest outcomes.

Every slice under `tests/fixtures/oss/` is a verbatim excerpt from a
permissively-licensed upstream source; `PROVENANCE.yaml` carries the
repo, pinned upstream ref, license and sha256 of the exact bytes.
A hash mismatch means the slice was edited to pass — that is the
fabrication mode this corpus exists to rule out.

Negative slices under `tests/fixtures/oss-negative/` are malformed or
unsupported real-world input — each asserts a specific failure mode
(parse status / unsupported version), never a crash and never a
guessed finding.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.scan import scan_project

ROOT = Path(__file__).resolve().parents[1]
OSS = ROOT / "tests" / "fixtures" / "oss"
OSS_NEG = ROOT / "tests" / "fixtures" / "oss-negative"

# Permissive licenses only — each slice names its license and upstream
# attribution in PROVENANCE.yaml (CC-BY-4.0 is honored via the
# source_repo/upstream_ref fields).
LICENSE_ALLOWLIST = frozenset({
    "Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause",
    "CC0-1.0", "CC-BY-4.0",
})


def _manifest() -> list[dict]:
    data = yaml.safe_load((OSS / "manifest.yaml").read_text("utf-8"))
    return list(data["slices"])


def _neg_manifest() -> list[dict]:
    data = yaml.safe_load(
        (OSS_NEG / "manifest.yaml").read_text("utf-8"))
    return list(data["cases"])


def _slice_dir(name: str, base: Path = OSS) -> Path:
    return base / name


def _canonical_bytes(path: Path) -> bytes:
    """Slice bytes with LF line endings — provenance hashes pin the
    canonical LF form so the check survives platform checkout EOL
    (`core.autocrlf=input` gives Windows checkouts CRLF on disk)."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_manifest_sorted_and_complete() -> None:
    entries = _manifest()
    assert [e["name"] for e in entries] == sorted(
        e["name"] for e in entries), "manifest must enumerate in sorted order"
    assert len(entries) >= 12
    on_disk = sorted(
        p.parent.relative_to(OSS).as_posix()
        for p in OSS.rglob("slice.*"))
    assert [e["name"] for e in entries] == on_disk


@pytest.mark.parametrize(
    "entry", _manifest(), ids=lambda e: e["name"])
def test_slice_provenance_hash_and_license(entry: dict) -> None:
    d = _slice_dir(entry["name"])
    prov = yaml.safe_load((d / "PROVENANCE.yaml").read_text("utf-8"))
    for key in ("source_repo", "upstream_path", "upstream_ref",
                "license", "sha256", "extracted_at_note"):
        assert key in prov, f"{entry['name']}: missing {key}"
    assert prov["license"] in LICENSE_ALLOWLIST
    digest = hashlib.sha256(
        _canonical_bytes(d / entry["file"])).hexdigest()
    assert digest == prov["sha256"] == entry["sha256"], (
        f"{entry['name']}: slice bytes do not match provenance hash")


@pytest.mark.parametrize(
    "entry", _manifest(), ids=lambda e: e["name"])
def test_slice_pipeline_produces_declared_findings(entry: dict) -> None:
    if entry["domain"] == "graphql":
        from forge_doctor_api.lab.capabilities import extra_available
        if not extra_available("graphql"):
            pytest.skip("graphql extra absent — capability gap is explicit")
    report = scan_project(
        ProjectContext.from_root(_slice_dir(entry["name"])))
    ids = sorted({f.id for f in report.findings})
    assert ids == sorted(entry["expected_findings"]), (
        f"{entry['name']}: analyzer output drifted from declared "
        f"expectations — got {ids}")


def _doc_status(name: str, file: str, domain: str) -> str:
    """Domain-level document status for a negative slice."""
    ctx = ProjectContext.from_root(_slice_dir(name, OSS_NEG))
    if domain == "openapi":
        from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
        return load_openapi_project(ctx).documents[0].status.value
    if domain == "asyncapi":
        from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
        return load_asyncapi_project(ctx).documents[0].status.value
    if domain == "grpc":
        from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
        return load_grpc_project(ctx, [file]).documents[0].status.value
    if domain == "graphql":
        from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
        return load_graphql_project(ctx, [file]).documents[0].status.value
    raise AssertionError(f"unknown domain {domain}")


@pytest.mark.parametrize(
    "case", _neg_manifest(), ids=lambda e: e["name"])
def test_negative_case_failure_mode(case: dict) -> None:
    if case["domain"] == "graphql":
        from forge_doctor_api.lab.capabilities import extra_available
        if not extra_available("graphql"):
            pytest.skip("graphql extra absent — capability gap is explicit")
    # the analyzer must not crash — any exception fails the test
    status = _doc_status(case["name"], case["file"], case["domain"])
    assert status == case["expect_status"], (
        f"{case['name']}: expected {case['expect_status']}, got {status}")
    report = scan_project(
        ProjectContext.from_root(_slice_dir(case["name"], OSS_NEG)))
    ids = sorted({f.id for f in report.findings})
    assert ids == sorted(case["expected_findings"]), (
        f"{case['name']}: findings {ids} != declared {case['expected_findings']}")


@pytest.mark.parametrize(
    "case", _neg_manifest(), ids=lambda e: e["name"])
def test_negative_case_provenance_hash(case: dict) -> None:
    d = _slice_dir(case["name"], OSS_NEG)
    prov = yaml.safe_load((d / "PROVENANCE.yaml").read_text("utf-8"))
    digest = hashlib.sha256(
        _canonical_bytes(d / case["file"])).hexdigest()
    assert digest == prov["sha256"] == case["sha256"]
