"""Spec 069 — release/supply-chain: SBOM structure + release wiring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "factory"))

from sbom import build_sbom  # noqa: E402


def test_sbom_structure() -> None:
    sbom = build_sbom()
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    meta = sbom["metadata"]["component"]
    assert meta["name"] == "forge-doctor-api"
    assert meta["type"] == "application"


def test_sbom_declares_exactly_pyproject_deps() -> None:
    sbom = build_sbom()
    by_scope: dict[str, set[str]] = {}
    for comp in sbom["components"]:
        by_scope.setdefault(comp["scope"], set()).add(comp["name"])
    assert by_scope["required"] == {"typer", "rich", "pyyaml"}
    assert "graphql-core" in by_scope["optional"]
    assert "mcp" in by_scope["optional"]
    # every component is a declared dependency — no transitives claimed
    assert all(c["type"] == "library" and c["purl"].startswith("pkg:pypi/")
               for c in sbom["components"])
    deps = sbom["dependencies"][0]["dependsOn"]
    assert set(deps) == {c["bom-ref"] for c in sbom["components"]}


def test_release_workflow_contract() -> None:
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8")
    assert "workflow_dispatch" in wf
    assert 'tags: ["v*"]' in wf
    assert "python -m build" in wf
    assert "factory/sbom.py" in wf
    assert "sha256sum" in wf
    assert "attest-build-provenance" in wf
    assert "draft: true" in wf
    # never auto-publish
    assert "prerelease" not in wf or "draft" in wf


def test_dependency_review_wired() -> None:
    q = (ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8")
    assert "dependency-review-action" in q


def test_release_policy_doc_covers_surfaces() -> None:
    doc = (ROOT / "docs" / "release-policy.md").read_text(encoding="utf-8")
    for surface in ("schema_version", "DoctorReport", "doctor://",
                    "doctor.*", "checklist"):
        assert surface in doc


def test_sbom_check_gate() -> None:
    import subprocess
    committed = ROOT / "factory" / "artifacts" / "sbom.cdx.json"
    assert committed.exists(), "committed reference SBOM missing"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "factory" / "sbom.py"), "--check"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_sha256sums_round_trip(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "factory"))
    import sha256sums
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "pkg-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (dist / "pkg-0.1.0.tar.gz").write_bytes(b"sdist-bytes")
    assert sha256sums.main.__module__ == "sha256sums"
    entries = sha256sums._hashes(dist)
    assert sorted(entries) == [
        "pkg-0.1.0-py3-none-any.whl", "pkg-0.1.0.tar.gz"]
    rendered = sha256sums._render(entries)
    names = [line.split("  ", 1)[1] for line in rendered.splitlines()]
    assert names == sorted(names)
    assert all("  " in line for line in rendered.splitlines())


def test_release_docs_and_changelog() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.1.0]" in changelog
    assert "spec 079" in changelog
    release = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    assert "0.1.x" in release and "SHA256SUMS" in release
    evidence = (ROOT / "docs" / "release-evidence.md").read_text(
        encoding="utf-8")
    assert "16d14a5" in evidence  # initial HEAD at branch point


def test_quality_workflow_release_gates() -> None:
    q = (ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8")
    assert "factory/sbom.py --check" in q
    assert "factory/sha256sums.py --verify" in q
