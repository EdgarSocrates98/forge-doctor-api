"""Vendored installkit coverage — ``forge_doctor_api._installkit`` 1.0.6.

The engine is vendored byte-for-byte from
``the-forge/src/theforge/_installkit.py`` (canonical
``the-forge/scripts/installkit/forge_installkit.py`` modulo the
``_SOURCE_SHA256`` stamp) — these tests pin the install-2.1 behaviors
the wave-12 re-vendor brought in: gitless member discovery
(``MEMBER_MARKERS``), symlink/junction-safe walk, ignored dirs,
explicit-root precedence (§5.5), consolidated-plan ``exclude``, and the
``manifest_for`` install-2.1 fields. Pure seams only — no real installs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import forge_doctor_api
from forge_doctor_api import _installkit as kit

ROOT = Path(__file__).resolve().parents[1]


def _spec(render: Any = None) -> kit.ForgeSpec:
    return kit.ForgeSpec(
        forge_id="forge-doctor-api",
        package="forge_doctor_api",
        distribution="forge-doctor-api",
        cli_name="forge-doctor-api",
        python_spec=">=3.11",
        state_dir=".forge-doctor-api/install",
        mcp_command=("forge-doctor-api", "mcp"),
        mcp_server_name="forge-doctor-api",
        mcp_verify_tool="doctor.get_reliability",
        version_cmd=("--version",),
        render_assets=render,
        marker_files=(),
        marker_body="",
        user_state_dir="~/.forge-doctor-api",
        spawn_ok=True,
    )


def _ctx(
    root: Path,
    *,
    render: Any = None,
    dry_run: bool = True,
    exclude: tuple[str, ...] = (),
) -> kit.InstallContext:
    spec = _spec(render)
    return kit.InstallContext(
        spec=spec,
        scope="project",
        root=root,
        state_dir=root / ".forge-doctor-api" / "install",
        profile="recommended",
        hosts=("devin",),
        dry_run=dry_run,
        options={},
        exclude=exclude,
    )


# --------------------------------------------------------------------------
# Vendored stamp — drift gates
# --------------------------------------------------------------------------


def test_installkit_version_and_source_stamp() -> None:
    """Drift gate: the vendored copy carries the upstream version and the
    canonical-source sha prefix — never the literal 'canonical' marker."""
    assert kit._INSTALLKIT_VERSION == "1.0.6"
    assert kit._SOURCE_SHA256 not in ("", "canonical")
    assert len(kit._SOURCE_SHA256) >= 12


def test_packaged_and_checkout_copies_stay_byte_identical() -> None:
    """``src/_installkit.py`` == ``scripts/forge_installkit.py`` — the two
    vendored copies never drift apart (also guarded by
    test_forge_install.test_package_carries_install_surface)."""
    packaged = ROOT / "src" / "forge_doctor_api" / "_installkit.py"
    checkout = ROOT / "scripts" / "forge_installkit.py"
    assert packaged.read_bytes() == checkout.read_bytes()


# --------------------------------------------------------------------------
# discover_projects() — gitless member discovery (install-2.1 / §5.5)
# --------------------------------------------------------------------------


def test_discover_projects_git_only_repos(tmp_path: Path) -> None:
    (tmp_path / "a" / ".git").mkdir(parents=True)
    (tmp_path / "b" / ".git").mkdir(parents=True)
    assert {p.name for p in kit.discover_projects(tmp_path)} == {"a", "b"}


def test_discover_projects_gitless_members(tmp_path: Path) -> None:
    """A member no longer needs ``.git`` — project manifests count."""
    (tmp_path / "svc-py").mkdir()
    (tmp_path / "svc-py" / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "svc-js").mkdir()
    (tmp_path / "svc-js" / "package.json").write_text("{}")
    (tmp_path / "svc-forge").mkdir()
    (tmp_path / "svc-forge" / "forge.json").write_text("{}")
    (tmp_path / "plain").mkdir()  # no marker — not a member
    found = {p.name for p in kit.discover_projects(tmp_path)}
    assert found == {"svc-py", "svc-js", "svc-forge"}


def test_discover_projects_includes_root_when_it_is_a_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert tmp_path.resolve() in kit.discover_projects(tmp_path)


def test_discover_projects_never_descends_into_a_member(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    (outer / ".git").mkdir(parents=True)
    inner = outer / "inner"
    inner.mkdir()
    (inner / "pyproject.toml").write_text("[project]\nname='x'\n")
    found = kit.discover_projects(tmp_path)
    assert outer.resolve() in found
    assert inner.resolve() not in found


def test_discover_projects_skips_hidden_and_ignored_dirs(tmp_path: Path) -> None:
    for ignored in (".hidden", "node_modules", ".venv", "dist", "__pycache__"):
        d = tmp_path / ignored
        d.mkdir()
        (d / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert kit.discover_projects(tmp_path) == []


def test_discover_projects_never_follows_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "pyproject.toml").write_text("[project]\nname='x'\n")
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    found = {p.name for p in kit.discover_projects(tmp_path)}
    assert "real" in found
    assert "linked" not in found


def test_discover_projects_respects_max_depth(tmp_path: Path) -> None:
    deep = tmp_path / "l1" / "l2" / "l3"
    deep.mkdir(parents=True)
    (deep / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert kit.discover_projects(tmp_path, max_depth=1) == []
    assert {p.name for p in kit.discover_projects(tmp_path, max_depth=3)} == {"l3"}


# --------------------------------------------------------------------------
# resolve_scope — explicit root precedence (§5.5)
# --------------------------------------------------------------------------


def test_resolve_scope_explicit_root_is_authoritative_for_workspace(tmp_path: Path) -> None:
    """A workspace marker in an ANCESTOR can never pull the root above the
    explicit --root (the 1.0.4 ancestor walk could)."""
    ancestor = tmp_path / "ancestor"
    chosen = ancestor / "member"
    chosen.mkdir(parents=True)
    (ancestor / ".git").mkdir()
    out = kit.resolve_scope(_spec(), "workspace", chosen, chosen)
    assert out == chosen


def test_resolve_scope_project_needs_marker_or_explicit() -> None:
    # tmp_path lives under the repo (``--basetemp``), whose ancestors all
    # carry markers — a real marker-free cwd has to come from /tmp.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        bare = Path(td) / "bare"
        bare.mkdir()
        with pytest.raises(kit.InstallError) as exc:
            kit.resolve_scope(_spec(), "project", bare, None)
    assert exc.value.kind == kit.E_NOTREPO


def test_resolve_scope_project_explicit_root_wins(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert kit.resolve_scope(_spec(), "project", bare, bare) == bare


# --------------------------------------------------------------------------
# InstallContext.exclude — consolidated-plan conflict losers
# --------------------------------------------------------------------------

_ASSET = "skills/demo/SKILL.md"


def _render(ctx: kit.InstallContext) -> dict[str, bytes]:
    return {_ASSET: b"# x\n"}


def test_apply_skips_excluded_conflict_paths(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, render=_render, dry_run=False, exclude=(_ASSET,))
    receipt = kit.apply_install(ctx, approved=True)
    skipped = [f for f in receipt["managed_files"] if f["action"] == "skipped"]
    assert [f["path"] for f in skipped] == [_ASSET]
    assert "cross-forge conflict" in skipped[0]["note"]
    assert not (tmp_path / _ASSET).exists()
    check = next(c for c in receipt["checks"] if c["id"] == "cross-forge-conflicts")
    assert check["status"] == "PASS"


def test_plan_reports_excluded_paths_without_writing(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, render=_render, dry_run=True, exclude=(_ASSET,))
    doc = kit.plan(ctx)
    skipped = [f for f in doc["planned_files"] if f["action"] == "skipped"]
    assert [f["path"] for f in skipped] == [_ASSET]
    assert "excluded by the consolidated plan" in skipped[0]["note"]
    assert not (tmp_path / "skills").exists()


# --------------------------------------------------------------------------
# manifest_for — install-2.1 fields (v2)
# --------------------------------------------------------------------------


def test_manifest_for_accepts_install21_fields(tmp_path: Path) -> None:
    doc = kit.manifest_for(
        _spec(),
        install_root=tmp_path,
        venv=tmp_path / ".venv",
        version="0.3.4",
        source={"kind": "git-checkout", "path": str(tmp_path)},
        shim=None,
        installation_kind="content",
        install={"operations": ["apply"], "approval": "--yes"},
        depends_on=["the-forge"],
    )
    assert doc["installation_kind"] == "content"
    assert doc["install"] == {"operations": ["apply"], "approval": "--yes"}
    assert doc["depends_on"] == ["the-forge"]
    # ForgeSpec.mcp_verify_tool flows into the manifest's mcp block.
    assert doc["mcp"]["verify_tool"] == "doctor.get_reliability"


def test_manifest_for_rejects_bad_installation_kind(tmp_path: Path) -> None:
    with pytest.raises(kit.InstallError) as exc:
        kit.manifest_for(
            _spec(),
            install_root=tmp_path,
            venv=None,
            version="0.3.4",
            source={"kind": "git-checkout", "path": str(tmp_path)},
            shim=None,
            installation_kind="widget",
        )
    assert exc.value.kind == kit.E_UNSUPPORTED
    assert "widget" in str(exc.value)


# --------------------------------------------------------------------------
# forge.json declarations — bundled mirror parity + honest surface
# --------------------------------------------------------------------------


def test_forge_json_packaged_mirror_is_byte_identical() -> None:
    """``src/forge_doctor_api/forge.json`` is the wheel-bundled mirror of
    the checkout root ``forge.json`` — ``_bundled_json`` resolves it in
    installed wheels where no repo root exists."""
    root_doc = (ROOT / "forge.json").read_bytes()
    bundled = (ROOT / "src" / "forge_doctor_api" / "forge.json").read_bytes()
    assert bundled == root_doc


def test_forge_json_declared_surface_is_honest() -> None:
    """Every declared flag/operation/host/scope/profile exists for real —
    the install-2.1 contract never over-declares."""
    cfg = json.loads((ROOT / "forge.json").read_text(encoding="utf-8"))
    assert cfg["installation_kind"] in kit.INSTALLATION_KINDS
    surf = cfg["install"]
    assert surf["approval"] == "--yes"
    assert set(surf["operations"]) <= {
        "plan",
        "apply",
        "status",
        "doctor",
        "repair",
        "update",
        "uninstall",
        "auto",
        "mcp-verify",
    }
    # The eight orchestrator request flags must all be honored.
    for flag in (
        "--scope",
        "--root",
        "--host",
        "--profile",
        "--components",
        "--gateway-profile",
        "--yes",
        "--dry-run",
    ):
        assert flag in surf["flags"], flag
    assert set(surf["hosts"]) == {"claude", "devin", "codex", "copilot"}
    assert cfg["depends_on"] == []
    assert cfg["mcp_verify_tool"] == "doctor.get_reliability"


def test_forge_json_version_matches_package() -> None:
    cfg = json.loads((ROOT / "forge.json").read_text(encoding="utf-8"))
    assert cfg["version"] == forge_doctor_api.__version__


def test_forge_json_declared_flags_are_argparse_safe() -> None:
    """Declared flags are ``--long`` names only."""
    cfg = json.loads((ROOT / "forge.json").read_text(encoding="utf-8"))
    for flag in cfg["install"]["flags"]:
        assert flag.startswith("--"), flag
