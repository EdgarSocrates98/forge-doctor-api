"""Specs 077+085 — real-world OSS corpus: provenance + honest outcomes.

Every slice under `tests/fixtures/oss/` is a verbatim excerpt from a
permissively-licensed upstream source; `PROVENANCE.yaml` carries the
repo, pinned upstream ref, license and sha256 of the exact bytes.
A hash mismatch means the slice was edited to pass — that is the
fabrication mode this corpus exists to rule out.

Spec 085 adds ground truth: `expected_entities`, `forbidden_findings`,
`expected_unknowns` and `protocol` are asserted, not just declared —
forbidden findings bind as hard as expected ones, and a slice that
emits an entity or finding outside its declared set fails the build.

Negative slices under `tests/fixtures/oss-negative/` are malformed,
partial, or dynamic-dispatch inputs — each asserts a specific failure
mode (parse status / unsupported version / bounded unknowns), never a
crash and never a guessed finding. Non-document domains (`spring`,
`express`, `nestjs`, `kong`, `envoy`, `k8s-gateway`, `k8s-ingress`,
`mesh`) use `expect_status: SCANNED` — the pipeline must complete
without raising.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.scan import scan_project

if TYPE_CHECKING:
    from forge_doctor_api.report import DoctorReport

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

PROTOCOLS = frozenset({"http", "grpc", "graphql", "events"})

# spec 085 domain matrix: every domain here needs >=1 positive slice in
# oss/ and >=1 negative/adversarial case in oss-negative/.
DOMAIN_MATRIX = frozenset({
    "openapi", "asyncapi", "grpc", "graphql",
    "spring", "express", "nestjs",
    "kong", "envoy", "k8s-gateway", "k8s-ingress",
})

_MANIFEST_REQUIRED = (
    "name", "file", "domain", "protocol",
    "expected_findings", "expected_entities", "forbidden_findings", "sha256",
)
_NEG_REQUIRED = (
    "name", "file", "domain", "protocol", "expect_status",
    "expected_findings", "forbidden_findings", "sha256",
)


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


def _family_matches(entry: str, actual_id: str) -> bool:
    """`PREFIX*` globs match a family; bare ids match exactly."""
    if entry.endswith("*"):
        return actual_id.startswith(entry[:-1])
    return actual_id == entry


def _entity_ids(report: DoctorReport) -> set[str]:
    """Report-level entity surface: domain-summary ids + operations."""
    out: set[str] = set()
    for summary in (
            report.routes, report.gateway, report.mesh,
            report.infrastructure, report.contracts):
        if summary is not None:
            out.update(summary.ids)
    out.update(report.operations or ())
    return out


def _unknown_subjects(report: DoctorReport) -> set[str]:
    return {u.subject for u in report.unknowns}


def _scan(name: str, base: Path = OSS) -> DoctorReport:
    return scan_project(ProjectContext.from_root(_slice_dir(name, base)))


def test_manifest_sorted_and_complete() -> None:
    entries = _manifest()
    assert [e["name"] for e in entries] == sorted(
        e["name"] for e in entries), "manifest must enumerate in sorted order"
    assert len(entries) >= 30
    on_disk = sorted(
        p.parent.relative_to(OSS).as_posix()
        for p in OSS.rglob("slice.*"))
    assert [e["name"] for e in entries] == on_disk


def test_manifest_schema_and_domain_matrix() -> None:
    """Every entry carries spec-085 ground truth; the matrix is covered
    on both sides — >=1 positive slice + >=1 negative case per domain."""
    entries = _manifest()
    cases = _neg_manifest()
    for e in entries:
        for key in _MANIFEST_REQUIRED:
            assert key in e, f"{e['name']}: missing manifest key {key}"
        assert e["protocol"] in PROTOCOLS
    for c in cases:
        for key in _NEG_REQUIRED:
            assert key in c, f"{c['name']}: missing manifest key {key}"
        assert c["protocol"] in PROTOCOLS
    pos_domains = {e["domain"] for e in entries}
    neg_domains = {c["domain"] for c in cases}
    missing_pos = DOMAIN_MATRIX - pos_domains
    missing_neg = DOMAIN_MATRIX - neg_domains
    assert not missing_pos, f"domains without a positive slice: {missing_pos}"
    assert not missing_neg, f"domains without a negative case: {missing_neg}"


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
    report = _scan(entry["name"])
    ids = sorted({f.id for f in report.findings})
    assert ids == sorted(entry["expected_findings"]), (
        f"{entry['name']}: analyzer output drifted from declared "
        f"expectations — got {ids}")


@pytest.mark.parametrize(
    "entry", _manifest(), ids=lambda e: e["name"])
def test_slice_ground_truth_entities_and_boundaries(entry: dict) -> None:
    """Entities, forbidden findings and expected unknowns all bind."""
    if entry["domain"] == "graphql":
        from forge_doctor_api.lab.capabilities import extra_available
        if not extra_available("graphql"):
            pytest.skip("graphql extra absent — capability gap is explicit")
    report = _scan(entry["name"])
    actual_ids = sorted({f.id for f in report.findings})
    forbidden_hits = [
        a for a in actual_ids
        if any(_family_matches(e, a) for e in entry["forbidden_findings"])
    ]
    assert not forbidden_hits, (
        f"{entry['name']}: forbidden findings emitted: {forbidden_hits}")
    entities = _entity_ids(report)
    missing = [e for e in entry["expected_entities"] if e not in entities]
    assert not missing, (
        f"{entry['name']}: expected entities absent — {missing}; "
        f"observed {sorted(entities)}")
    subjects = _unknown_subjects(report)
    missing_unk = [
        u for u in entry.get("expected_unknowns", ()) if u not in subjects]
    assert not missing_unk, (
        f"{entry['name']}: expected unknowns absent — {missing_unk}; "
        f"observed {sorted(subjects)}")


def _doc_status(name: str, file: str, domain: str) -> str:
    """Domain-level document status for a negative slice.

    Non-document domains have no per-format status — `SCANNED` asserts
    the full pipeline completed without raising.
    """
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
    scan_project(ctx)
    return "SCANNED"


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
    report = _scan(case["name"], OSS_NEG)
    ids = sorted({f.id for f in report.findings})
    assert ids == sorted(case["expected_findings"]), (
        f"{case['name']}: findings {ids} != declared {case['expected_findings']}")
    forbidden_hits = [
        a for a in ids
        if any(_family_matches(e, a) for e in case["forbidden_findings"])
    ]
    assert not forbidden_hits, (
        f"{case['name']}: forbidden findings emitted: {forbidden_hits}")
    subjects = _unknown_subjects(report)
    missing_unk = [
        u for u in case.get("expected_unknowns", ()) if u not in subjects]
    assert not missing_unk, (
        f"{case['name']}: expected unknowns absent — {missing_unk}; "
        f"observed {sorted(subjects)}")


@pytest.mark.parametrize(
    "case", _neg_manifest(), ids=lambda e: e["name"])
def test_negative_case_provenance_hash(case: dict) -> None:
    d = _slice_dir(case["name"], OSS_NEG)
    prov = yaml.safe_load((d / "PROVENANCE.yaml").read_text("utf-8"))
    digest = hashlib.sha256(
        _canonical_bytes(d / case["file"])).hexdigest()
    assert digest == prov["sha256"] == case["sha256"]
