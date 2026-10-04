"""Spec 064 — knowledge pack manifest lifecycle."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.knowledge.manifest import (
    BUILTIN_ID,
    PackManifest,
    PackStatus,
    compatible,
    list_packs,
    load_manifest,
)


def _pack(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "forge-doctor-knowledge.toml").write_text(body, "utf-8")
    return root


GOOD = """
[knowledge]
id = "acme-rules"
version = "1.2.0"
doctor_compat = ">=0.1"
provides = ["security"]
requires = []
"""


def test_happy_manifest(tmp_path: Path) -> None:
    d = _pack(tmp_path / "p", GOOD)
    manifest, errors = load_manifest(d)
    assert errors == ()
    assert manifest is not None
    assert manifest.id == "acme-rules"
    assert manifest.version == "1.2.0"
    ok, _ = compatible(manifest, engine="0.1.0")
    assert ok


def test_missing_manifest_listed(tmp_path: Path) -> None:
    manifest, errors = load_manifest(tmp_path)
    assert manifest is None
    assert any("manifest not found" in e for e in errors)


def test_malformed_never_partial_load(tmp_path: Path) -> None:
    d = _pack(tmp_path / "bad", """
[knowledge]
id = "INVALID ID!"
version = "not-semver"
provides = "not-a-list"
""")
    manifest, errors = load_manifest(d)
    assert manifest is None
    assert len(errors) >= 3  # id, version, provides all listed


def test_bad_toml_listed(tmp_path: Path) -> None:
    d = _pack(tmp_path / "b2", "{not toml")
    manifest, errors = load_manifest(d)
    assert manifest is None and errors


def test_incompatible_skipped_with_unknown(tmp_path: Path) -> None:
    d = _pack(tmp_path / "old", """
[knowledge]
id = "old-pack"
version = "1.0.0"
doctor_compat = ">=9.9"
""")
    listings, unknowns = list_packs((d,), include_builtin=False)
    assert listings[0].status is PackStatus.INCOMPATIBLE
    assert any(u.subject == "old-pack" for u in unknowns)


def test_conflict_deterministic_winner(tmp_path: Path) -> None:
    first = _pack(tmp_path / "a", GOOD)
    second = _pack(tmp_path / "b", GOOD)
    listings, _ = list_packs((first, second), include_builtin=False)
    statuses = {li.source: li.status for li in listings}
    assert statuses[str(first)] is PackStatus.ACTIVE
    assert statuses[str(second)] is PackStatus.CONFLICT
    assert "first in precedence" in listings[1].details


def test_builtin_listed_and_pinned(tmp_path: Path) -> None:
    listings, _ = list_packs(())
    builtin = [li for li in listings if li.manifest
               and li.manifest.id == BUILTIN_ID]
    assert len(builtin) == 1
    assert builtin[0].status is PackStatus.ACTIVE
    assert "pinned" in builtin[0].details


def test_builtin_shadowed_by_explicit(tmp_path: Path) -> None:
    d = _pack(tmp_path / "mine", """
[knowledge]
id = "builtin"
version = "9.9.9"
""")
    listings, _ = list_packs((d,))
    by_id = {li.source: li for li in listings}
    assert by_id[str(d)].status is PackStatus.ACTIVE
    real = [li for li in listings if li.source != str(d)]
    assert real[0].status is PackStatus.CONFLICT


def test_semver_range_ops() -> None:
    m = PackManifest(id="x", version="1.0.0",
                     doctor_compat=">=0.1,<0.3")
    assert compatible(m, "0.2.0")[0]
    assert not compatible(m, "0.3.0")[0]
    assert not compatible(m, "0.0.9")[0]
    m2 = PackManifest(id="x", version="1.0.0", doctor_compat="!=0.1.0")
    assert compatible(m2, "0.1.1")[0]
    assert not compatible(m2, "0.1.0")[0]
