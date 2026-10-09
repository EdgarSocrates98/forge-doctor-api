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
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=env, timeout=60)


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
    proc = _run("install", "--root", str(target), "--dry-run",
                env_home=home)
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
    assert _json(proc)["status"] == "completed"
    mcp = json.loads((target / ".mcp.json").read_text())
    entry = mcp["mcpServers"]["forge-doctor-api"]
    assert entry["command"] == "forge-doctor-api"
    assert entry["args"] == ["mcp"]
    assert "forge-doctor-api:managed:begin" in (
        target / "AGENTS.md").read_text(encoding="utf-8")


def test_apply_preserves_foreign_mcp_servers(target: Path, home: Path) -> None:
    (target / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"other": {"command": "x"}}, "unrelated": True}))
    proc = _run("install", "--root", str(target), "--yes", env_home=home)
    assert proc.returncode == 0
    doc = json.loads((target / ".mcp.json").read_text())
    assert doc["mcpServers"]["other"] == {"command": "x"}
    assert doc["unrelated"] is True


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


def test_user_text_outside_marker_is_not_drift(target: Path,
                                               home: Path) -> None:
    _run("install", "--root", str(target), "--yes", env_home=home)
    ag = target / "AGENTS.md"
    ag.write_text(ag.read_text(encoding="utf-8") + "\n# mine\n",
                  encoding="utf-8")
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
    assert new["mcpServers"]["forge-doctor-api"]["command"] == (
        "forge-doctor-api")
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


def test_package_surface_unchanged() -> None:
    """RC invariant: the adapter lives in scripts/, so the package exposes
    no new CLI verb — guard the boundary the design depends on."""
    src = ROOT / "src" / "forge_doctor_api"
    assert not (src / "_installkit.py").exists()
    assert not (src / "install").exists()
