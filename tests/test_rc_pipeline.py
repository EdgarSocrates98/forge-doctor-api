"""Spec 089 — RC pipeline: release manifest, provenance, dirty-tree
policy, version gate, self-scan shape gate, release smoke."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "factory"
sys.path.insert(0, str(FACTORY))

import provenance  # noqa: E402
import release_manifest  # noqa: E402
import self_scan  # noqa: E402
import version_gate  # noqa: E402

import forge_doctor_api  # noqa: E402

# ---------- release manifest ----------


def test_manifest_required_fields() -> None:
    m = release_manifest.build_manifest(dist_dir=ROOT / "no-such-dist")
    assert m["manifest_version"] == 1
    assert m["package"] == "forge-doctor-api"
    assert m["version"]
    assert m["python_requires"].startswith(">=")
    assert m["python_classified"]
    assert m["contract_family"] == "forge-contracts"
    assert m["contract_version"] == "1"
    assert m["forge_protocol_version"] >= 1
    assert m["cli_command_count"] > 0
    assert m["mcp_tool_count"] > 0
    assert m["schema_ids"]
    assert isinstance(m["artifacts"], list)
    assert m["dirty_tree"] in (True, False, None)


def test_manifest_deterministic_render() -> None:
    a = release_manifest._render(
        release_manifest.build_manifest(dist_dir=ROOT / "nope"))
    b = release_manifest._render(
        release_manifest.build_manifest(dist_dir=ROOT / "nope"))
    assert a == b


def test_manifest_rc_refused_on_dirty_tree(monkeypatch) -> None:
    monkeypatch.setattr(release_manifest, "_git_dirty", lambda: True)
    with pytest.raises(SystemExit):
        release_manifest.build_manifest(rc=True)
    m = release_manifest.build_manifest(rc=True, allow_dirty=True)
    assert m["rc"] is True
    assert m["dirty_tree"] is True


def test_manifest_rc_refused_when_git_unprovable(monkeypatch) -> None:
    """No git state -> dirty_tree None -> refusal (unknown is not
    clean)."""
    monkeypatch.setattr(release_manifest, "_git_dirty", lambda: None)
    with pytest.raises(SystemExit):
        release_manifest.build_manifest(rc=True)


def test_manifest_rc_ok_on_clean_tree(monkeypatch) -> None:
    monkeypatch.setattr(release_manifest, "_git_dirty", lambda: False)
    m = release_manifest.build_manifest(rc=True)
    assert m["rc"] is True and m["dirty_tree"] is False


def test_manifest_check_volatile_fields_excluded(tmp_path: Path) -> None:
    m = release_manifest.build_manifest(dist_dir=ROOT / "nope")
    base = tmp_path / "manifest.json"
    base.write_text(release_manifest._render(m), encoding="utf-8")
    # volatile drift must not fail the check: git state + digests
    changed = dict(m)
    changed["git_head"] = "0" * 40
    changed["dirty_tree"] = True
    changed["rc"] = True
    changed["artifacts"] = [{"filename": "a.whl", "sha256": "f" * 64}]
    baseline = dict(m, artifacts=[{"filename": "a.whl",
                                   "sha256": "0" * 64}])
    assert release_manifest._diff(
        release_manifest._normalize(baseline),
        release_manifest._normalize(changed)) == []
    # artifact filename drift IS identity drift — must fail
    renamed = dict(changed, artifacts=[{"filename": "b.whl",
                                        "sha256": "f" * 64}])
    assert release_manifest._diff(
        release_manifest._normalize(baseline),
        release_manifest._normalize(renamed))
    # non-volatile drift must fail
    drifted = dict(changed, version="9.9.9")
    assert release_manifest._diff(
        release_manifest._normalize(baseline),
        release_manifest._normalize(drifted))


def test_manifest_artifact_digests(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "forge_doctor_api-0.1.0-py3-none-any.whl").write_bytes(b"W")
    (dist / "forge_doctor_api-0.1.0.tar.gz").write_bytes(b"S")
    m = release_manifest.build_manifest(dist_dir=dist)
    names = [a["filename"] for a in m["artifacts"]]
    assert "forge_doctor_api-0.1.0-py3-none-any.whl" in names
    assert "forge_doctor_api-0.1.0.tar.gz" in names
    assert all(len(a["sha256"]) == 64 for a in m["artifacts"])


# ---------- provenance ----------


def test_provenance_deterministic_shape() -> None:
    a = provenance.build_provenance(dist_dir=ROOT / "nope")
    b = provenance.build_provenance(dist_dir=ROOT / "nope")
    assert provenance._render(a) == provenance._render(b)
    assert a["_type"].endswith("in-toto.io/Statement/v1")
    assert a["predicate"]["build"]["commands"] == ["python -m build"]
    assert a["predicate"]["tools"]["forge_doctor_api"]
    assert a["predicate"]["source"]["revision"]


def test_provenance_builder_ids(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert provenance._builder_id() == "local-build"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    assert provenance._builder_id() == (
        "https://github.com/o/r/actions/runs/42")


def test_provenance_subjects_from_dist(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "forge_doctor_api-0.1.0-py3-none-any.whl").write_bytes(b"W")
    p = provenance.build_provenance(dist_dir=dist)
    assert p["subject"][0]["name"].endswith(".whl")
    assert len(p["subject"][0]["digest"]["sha256"]) == 64


# ---------- version gate ----------


def test_version_gate_current_tree_consistent() -> None:
    sources = version_gate.gather(ROOT / "no-such-dist")
    v = forge_doctor_api.__version__
    assert sources["pyproject"] == v
    assert sources["__init__.__version__"] == v
    assert sources["sdk.SDK_VERSION"] == v
    assert len({v for v in sources.values()}) == 1


def test_version_gate_detects_dist_divergence(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "forge_doctor_api-9.9.9-py3-none-any.whl").write_bytes(b"x")
    sources = version_gate.gather(dist)
    divergent = {k: v for k, v in sources.items()
                 if v != sources["pyproject"]}
    assert "dist:forge_doctor_api-9.9.9-py3-none-any.whl" in divergent


# ---------- self-scan shape gate ----------


def _report(findings, unknowns=()) -> dict:
    return {
        "schema_version": "1.0", "tool_version": "0.1.0",
        "knowledge_versions": {"k": "v"}, "gate_passed": True,
        "gate_failures": [],
        "findings": findings,
        "unknowns": list(unknowns),
    }


def _finding(i: str, **kw) -> dict:
    return {"id": i, "severity": "HIGH", "confidence": "MEDIUM",
            "entity_ids": ["op:a"], "description": kw.get("d", "x"),
            "evidence": [{"line": kw.get("line", 1)}],
            "source_location": {"path": "f", "line": kw.get("line", 1)}}


def test_self_scan_shape_ignores_volatile_fields() -> None:
    a = _report([_finding("APISEC001", line=1, d="text one")])
    b = _report([_finding("APISEC001", line=99, d="text two")])
    assert self_scan._shape(a) == self_scan._shape(b)


def test_self_scan_shape_detects_identity_drift() -> None:
    a = _report([_finding("APISEC001")])
    b = _report([_finding("APISEC001"), _finding("APISEC004")])
    diffs = self_scan._diff_shape(
        self_scan._shape(a), self_scan._shape(b))
    assert any("APISEC004" in d for d in diffs)
    c = _report([dict(_finding("APISEC001"), entity_ids=["op:other"])])
    assert self_scan._diff_shape(
        self_scan._shape(a), self_scan._shape(c))


def test_self_scan_shape_detects_gate_drift() -> None:
    a = _report([])
    b = _report([], unknowns=())
    b["gate_passed"] = False
    assert self_scan._diff_shape(
        self_scan._shape(a), self_scan._shape(b))


# ---------- release smoke ----------


def test_release_smoke_requires_a_wheel(tmp_path: Path) -> None:
    import release_smoke
    with pytest.raises(SystemExit):
        release_smoke._wheel(tmp_path)


def test_release_smoke_picks_the_wheel(tmp_path: Path) -> None:
    import release_smoke
    (tmp_path / "forge_doctor_api-0.1.0-py3-none-any.whl").write_bytes(
        b"x")
    assert release_smoke._wheel(tmp_path).name.endswith(".whl")
