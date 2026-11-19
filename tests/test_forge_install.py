"""Portable install lifecycle — scripts-level adapter tests.

``scripts/forge_install.py`` is the checkout-level entrypoint for the
``forge/*`` installation contract v1. It exists outside ``src/`` because the
package boundary (``test_boundary.py``) bans ``os``/``subprocess`` imports
and the RC window forbids new CLI commands. Verbs, receipts and the
ownership ledger are identical to sibling forges' in-package adapters.

Tests drive the script as a subprocess — never imported — so they exercise
the real operator path. ``FORGE_HOME_OVERRIDE`` isolates the registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "forge_install.py"


def _run(*args: str, env_home: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_home is not None:
        env["FORGE_HOME_OVERRIDE"] = str(env_home)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60
    )


@pytest.fixture()
def target(tmp_path: Path) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    (root / ".git").mkdir()
    return root


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    return h


def _json(proc: subprocess.CompletedProcess) -> dict:
    assert proc.stdout.strip(), proc.stderr
    return json.loads(proc.stdout)


def test_dry_run_plans_without_mutating(target: Path, home: Path) -> None:
    proc = _run("install", "--root", str(target), "--dry-run", env_home=home)
    assert proc.returncode == 0, proc.stderr
    doc = _json(proc)
    assert doc["status"] == "planned"
    assert doc["schema"] == "forge/InstallReceipt/v1"
    assert not (target / ".mcp.json").exists()
    assert not (target / "AGENTS.md").exists()


def test_apply_requires_approval(target: Path, home: Path) -> None:
    proc = _run("install", "--root", str(target), env_home=home)
    assert proc.returncode == 1
    doc = _json(proc)
    assert doc["error"]["kind"] == "FORGE-INSTALL-PLAN-NOT-APPROVED"


def test_apply_writes_managed_regions(target: Path, home: Path) -> None:
    proc = _run("install", "--root", str(target), "--yes", env_home=home)
    assert proc.returncode == 0, proc.stderr
    receipt = _json(proc)
    assert receipt["status"] == "completed"
    mcp = json.loads((target / ".mcp.json").read_text())
    entry = mcp["mcpServers"]["forge-doctor-api"]
    # §9.3 — the managed key never launches through a PATH lookup: with no
    # registered shim the resolver falls back to `python -m` (absolute).
    assert entry["command"] == sys.executable
    assert Path(entry["command"]).is_absolute()
    assert entry["args"] == ["-m", "forge_doctor_api", "mcp"]
    # Consumer docs moved to the forge_context layer: `forge:*` blocks +
    # the shared workspace registry, not `forge-doctor-api:managed`.
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "forge:forge-doctor-api:begin" in agents
    assert "forge:ecosystem:begin" in agents
    reg = json.loads((target / ".forge" / "context" / "registry.json").read_text())
    assert reg["schema"] == "forge/context-registry/v1"
    entry = next(e for e in reg["forges"] if e["forge_id"] == "forge-doctor-api")
    assert entry["kind"] == "diagnostic-provider"
    assert {c["id"] for c in receipt["checks"]} >= {"context-registry", "consumer-docs"}


def test_apply_preserves_foreign_mcp_servers(target: Path, home: Path) -> None:
    (target / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}, "unrelated": True})
    )
    proc = _run("install", "--root", str(target), "--yes", env_home=home)
    assert proc.returncode == 0
    doc = json.loads((target / ".mcp.json").read_text())
    assert doc["mcpServers"]["other"] == {"command": "x"}
    assert doc["unrelated"] is True


# --------------------------------------------------------------------------
# cycle 16.1 — incremental reinstall, InstallLifecycle/v1 vocabulary,
# minimal L0 context blocks
# --------------------------------------------------------------------------

# Closed receipt vocabulary of ``forge/InstallLifecycle/v1`` (the-forge
# ``install/lifecycle.py`` — mirrored here as a pin: a receipt whose
# ``status``/``verification``/``checks`` stay inside these sets always
# derives a named lifecycle state, never the "outside vocabulary" branch).
_LIFECYCLE_RECEIPT_STATUSES = {
    "planned",
    "blocked",
    "refused",
    "unsupported",
    "completed",
    "failed",
    "unverified",
}
_LIFECYCLE_CHECK_STATUSES = {"PASS", "FAIL", "BLOCKED", "UNVERIFIED", "NOT_APPLICABLE"}
_LIFECYCLE_HEALTH_STATUSES = {"healthy", "degraded", "broken", "unverified"}


def _derive_state(receipt: dict) -> str:
    """The ``forge/InstallLifecycle/v1`` ``receipt_state`` mapping, reduced
    to the branches this adapter can emit."""
    status = str(receipt.get("status") or "")
    verification = str((receipt.get("verification") or {}).get("status") or "")
    assert status in _LIFECYCLE_RECEIPT_STATUSES, f"{status!r} outside the lifecycle vocabulary"
    if status == "planned":
        return "planned"
    if status in {"blocked", "refused", "unsupported"}:
        return "blocked"
    if status == "completed":
        if verification == "PASS":
            return "verified"
        if verification == "FAIL":
            return "failed"
        return "applied"
    if status == "failed":
        checks = [c for c in receipt.get("checks") or [] if isinstance(c, dict)]
        if checks and all(
            c.get("status") in ("BLOCKED", "UNVERIFIED", "NOT_APPLICABLE") for c in checks
        ):
            return "blocked"
        return "failed"
    return "unverified"


def test_reinstall_preserves_registered_shim(target: Path, home: Path) -> None:
    registry = home / ".forge" / "installations"
    registry.mkdir(parents=True)
    manifest = registry / "forge-doctor-api.json"
    shim = str(home / "bin" / "forge-doctor-api")
    manifest.write_text(json.dumps({"cli": {"shim": shim}}))
    for _ in range(2):
        proc = _run("install", "--root", str(target), "--yes", env_home=home)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(manifest.read_text())["cli"]["shim"] == shim
        entry = json.loads((target / ".mcp.json").read_text())["mcpServers"]["forge-doctor-api"]
        assert entry == {"command": shim, "args": ["mcp"]}


def test_reinstall_is_incremental(target: Path, home: Path) -> None:
    """§7.4 — a second install re-touches nothing byte-identical: the
    receipt's ``counts`` reports zero writes/zero bytes honestly."""
    first = _json(_run("install", "--root", str(target), "--yes", env_home=home))
    assert first["status"] == "completed"
    assert "counts" in first and "written" in first["counts"]
    mcp_before = (target / ".mcp.json").read_bytes()
    agents_before = (target / "AGENTS.md").read_bytes()

    second = _json(_run("install", "--root", str(target), "--yes", env_home=home))
    assert second["status"] == "completed"
    counts = second["counts"]
    assert counts["written"] == 0
    assert counts["written_bytes"] == 0
    # Managed surfaces stay byte-identical — reinstalls are not rewrites.
    assert (target / ".mcp.json").read_bytes() == mcp_before
    assert (target / "AGENTS.md").read_bytes() == agents_before
    proc = _run("status", "--root", str(target), env_home=home)
    assert _json(proc)["status"] == "healthy"


def test_receipt_vocabulary_is_lifecycle_compatible(target: Path, home: Path) -> None:
    """Every doc this adapter emits stays inside the closed
    ``forge/InstallLifecycle/v1`` vocabulary — the orchestrator's derived
    state never falls to the "outside vocabulary" branch."""
    plan = _json(_run("install", "--root", str(target), "--dry-run", env_home=home))
    assert plan["status"] in _LIFECYCLE_RECEIPT_STATUSES
    assert _derive_state(plan) == "planned"
    for check in plan.get("checks") or []:
        assert check["status"] in _LIFECYCLE_CHECK_STATUSES

    receipt = _json(_run("install", "--root", str(target), "--yes", env_home=home))
    assert receipt["status"] in _LIFECYCLE_RECEIPT_STATUSES
    for check in receipt["checks"]:
        assert check["status"] in _LIFECYCLE_CHECK_STATUSES
    assert receipt["verification"]["status"] in {"PASS", "FAIL", "UNVERIFIED", "BLOCKED"}
    assert _derive_state(receipt) == "verified"  # completed + PASS

    health = _json(_run("doctor", "--root", str(target), env_home=home))
    assert health["status"] in _LIFECYCLE_HEALTH_STATUSES
    for check in health["checks"]:
        assert check["status"] in _LIFECYCLE_CHECK_STATUSES


def test_agents_block_is_compact_l0(target: Path, home: Path) -> None:
    """§8.1/§8.2 — the AGENTS.md ``forge:*`` block is the routing-critical
    minimum (identity, domains, manifest + protocol pointers); interface
    detail lives in the manifest, not in the permanent context."""
    _run("install", "--root", str(target), "--yes", env_home=home)
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    start = agents.index("forge:forge-doctor-api:begin")
    end = agents.index("forge:forge-doctor-api:end")
    block = agents[start:end]
    assert "Domains:" in block
    assert ".forge/context/capabilities/forge-doctor-api.json" in block
    assert "AGENT_PROTOCOL.md" in block
    # Compact L0: no CLI/MCP/discovery enumeration inside the permanent
    # block — detail stays in the capability manifest it points to.
    assert "Discovery:" not in block
    assert "MCP server:" not in block


def test_status_doctor_round_trip(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    proc = _run("status", "--root", str(target), env_home=home)
    assert proc.returncode == 0
    assert _json(proc)["status"] == "healthy"
    proc = _run("doctor", "--root", str(target), env_home=home)
    assert proc.returncode == 0
    doc = _json(proc)
    assert doc["schema"] == "forge/InstallationHealth/v1"
    assert {c["id"] for c in doc["checks"]} >= {"ledger", "mcp-config"}


def test_user_text_outside_marker_is_not_drift(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    ag = target / "AGENTS.md"
    ag.write_text(ag.read_text(encoding="utf-8") + "\n# mine\n", encoding="utf-8")
    proc = _run("status", "--root", str(target), env_home=home)
    assert _json(proc)["status"] == "healthy"


def test_repair_restores_missing_mcp(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    mcp = target / ".mcp.json"
    doc = json.loads(mcp.read_text())
    doc["mcpServers"].pop("forge-doctor-api")
    doc["mcpServers"]["mine"] = {"command": "y"}
    mcp.write_text(json.dumps(doc))
    proc = _run("repair", "--root", str(target), env_home=home)
    assert proc.returncode == 0
    out = _json(proc)
    assert ".mcp.json" in out["repaired"]
    new = json.loads(mcp.read_text())
    # repair re-derives the managed key — same absolute resolved argv.
    assert new["mcpServers"]["forge-doctor-api"]["command"] == sys.executable
    assert new["mcpServers"]["forge-doctor-api"]["args"] == [
        "-m",
        "forge_doctor_api",
        "mcp",
    ]
    assert new["mcpServers"]["mine"] == {"command": "y"}


def test_uninstall_removes_owned_and_purges(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    proc = _run("uninstall", "--root", str(target), "--purge", env_home=home)
    assert proc.returncode == 0
    assert _json(proc)["status"] == "completed"
    assert not (target / ".mcp.json").exists()
    assert not (target / "AGENTS.md").exists()
    assert not (target / ".forge-doctor-api").exists()


def test_uninstall_keeps_user_modified(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    ag = target / "AGENTS.md"
    ag.write_text("# entirely mine\n", encoding="utf-8")
    _run("uninstall", "--root", str(target), env_home=home)
    assert ag.exists()  # sha mismatch → treated as user-owned


def test_update_latest_refused(home: Path) -> None:
    proc = _run("update", "--to", "latest", env_home=home)
    assert proc.returncode == 1
    assert _json(proc)["verification"]["status"] == "FAIL"


def test_mcp_verify_reports_env_independently(home: Path) -> None:
    proc = _run("mcp-verify", env_home=home)
    doc = _json(proc)
    check = doc["checks"][0]
    assert check["id"] == "mcp-handshake"
    assert check["status"] in ("PASS", "FAIL", "BLOCKED", "UNVERIFIED")
    assert proc.returncode == (1 if check["status"] == "FAIL" else 0)


def test_package_carries_install_surface() -> None:
    """cyc11.2 P2-002 (recorded RC exception): the wheel must carry the
    install engine — ``src/_installkit.py`` stays byte-identical to the
    canonical checkout copy so drift is impossible to hide."""
    src = ROOT / "src" / "forge_doctor_api"
    packaged = src / "_installkit.py"
    vendored = ROOT / "scripts" / "forge_installkit.py"
    assert packaged.is_file(), "wheel must carry _installkit.py"
    assert (src / "install" / "service.py").is_file()
    assert packaged.read_bytes() == vendored.read_bytes(), (
        "src/_installkit.py drifted from scripts/forge_installkit.py — "
        "re-vendor the canonical copy, never fork it"
    )
    # Same parity rule for the forge/context/v1 engine — the wheel copy
    # (`_forgecontext.py`) and the checkout adapter copy
    # (`scripts/forge_context.py`) never drift.
    assert (src / "_forgecontext.py").read_bytes() == (
        ROOT / "scripts" / "forge_context.py"
    ).read_bytes(), (
        "src/_forgecontext.py drifted from scripts/forge_context.py — "
        "re-vendor the canonical copy, never fork it"
    )


def test_register_writes_declared_install21_fields(target: Path, home: Path) -> None:
    """The checkout adapter's ``_register`` merges the forge.json install-2.1
    declarations into ``~/.forge/installations/`` — parity with the wheel
    surface (``test_install_cli.test_register_writes_declared_install21_fields``)."""
    proc = _run("install", "--root", str(target), "--yes", env_home=home)
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads(
        (home / ".forge" / "installations" / "forge-doctor-api.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["installation_kind"] == "content"
    assert manifest["install"]["approval"] == "--yes"
    assert "--scope" in manifest["install"]["flags"]
    assert manifest["depends_on"] == []
    assert manifest["mcp"]["verify_tool"] == "doctor.get_reliability"


def test_json_flag_emits_contract_doc(target: Path, home: Path) -> None:
    """``--json`` pins the JSON contract (orchestrator parity flag); on a
    pipe it is the no-op default."""
    proc = _run(
        "install", "--root", str(target), "--dry-run", "--json", env_home=home
    )
    assert proc.returncode == 0, proc.stderr
    doc = _json(proc)
    assert doc["status"] == "planned"


def test_no_input_still_requires_approval(target: Path, home: Path) -> None:
    """``--no-input`` suppresses prompting but never approves — fail-closed."""
    proc = _run("install", "--root", str(target), "--no-input", env_home=home)
    assert proc.returncode == 1
    doc = _json(proc)
    assert doc["error"]["kind"] == "FORGE-INSTALL-PLAN-NOT-APPROVED"
    assert not (target / ".mcp.json").exists()


def test_no_input_with_yes_applies(target: Path, home: Path) -> None:
    proc = _run(
        "install", "--root", str(target), "--no-input", "--yes", env_home=home
    )
    assert proc.returncode == 0, proc.stderr
    assert _json(proc)["status"] == "completed"


def test_subcommand_json_flag(target: Path, home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    proc = _run("status", "--root", str(target), "--json", env_home=home)
    assert proc.returncode == 0
    assert _json(proc)["status"] == "healthy"


def test_hosts_none_e_csv():
    """GAP-003: `none` nunca vira `all`; csv subconjunto e validado."""
    import importlib.util
    import sys
    from pathlib import Path

    import pytest

    spec = importlib.util.spec_from_file_location(
        "forge_install_script", Path(__file__).parents[1] / "scripts" / "forge_install.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_install_script"] = mod
    spec.loader.exec_module(mod)
    assert mod._hosts("all") == mod.HOSTS
    assert mod._hosts("none") == ()
    assert set(mod._hosts("claude,devin")) == {"claude", "devin"}
    with pytest.raises(mod.kit.InstallError):
        mod._hosts("nope")
