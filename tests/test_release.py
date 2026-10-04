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
