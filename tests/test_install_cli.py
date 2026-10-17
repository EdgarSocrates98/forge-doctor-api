"""``forge-doctor-api install`` — wheel-carried lifecycle tests (cyc11.2 P2-002).

The public CLI path is what ``forge-cli --native`` delegates to:
``{python} -m forge_doctor_api install ...``. These tests drive the Typer
app in-process (CliRunner — no sockets) and via ``python -m`` for the
catalog argv shape, with ``FORGE_HOME_OVERRIDE`` isolating the registry.

The checkout-level adapter ``scripts/forge_install.py`` is covered by
``test_forge_install.py``; here the same forge/* contract is proven on the
package surface.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forge_doctor_api.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


@pytest.fixture()
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "consumer"
    root.mkdir()
    (root / ".git").mkdir()
    monkeypatch.setenv("FORGE_HOME_OVERRIDE", str(tmp_path / "home"))
    return root


def _json(output: str) -> dict:
    assert output.strip(), "no JSON emitted"
    return json.loads(output)


def _invoke(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, ["install", *args])
    assert not result.exception or isinstance(result.exception, SystemExit), (
        result.exception
    )
    return result.exit_code, _json(result.stdout)


def test_dry_run_plans_without_mutating(target: Path) -> None:
    code, doc = _invoke("--root", str(target), "--dry-run")
    assert code == 0
    assert doc["status"] == "planned"
    assert doc["schema"] == "forge/InstallReceipt/v1"
    assert not (target / ".mcp.json").exists()
    assert not (target / "AGENTS.md").exists()


def test_apply_requires_approval(target: Path) -> None:
    result = runner.invoke(app, ["install", "--root", str(target)])
    assert result.exit_code == 1
    doc = _json(result.stdout)
    assert doc["error"]["kind"] == "FORGE-INSTALL-PLAN-NOT-APPROVED"


def test_apply_writes_managed_regions(target: Path) -> None:
    code, doc = _invoke("--root", str(target), "--yes")
    assert code == 0
    assert doc["status"] == "completed"
    mcp = json.loads((target / ".mcp.json").read_text())
    entry = mcp["mcpServers"]["forge-doctor-api"]
    assert entry["command"] == "forge-doctor-api"
    assert entry["args"] == ["mcp"]
    assert "forge-doctor-api:managed:begin" in (target / "AGENTS.md").read_text(
        encoding="utf-8"
    )


def test_status_doctor_round_trip(target: Path) -> None:
    _invoke("--root", str(target), "--yes")
    code, doc = _invoke("status", "--root", str(target))
    assert code == 0
    assert doc["status"] == "healthy"
    code, doc = _invoke("doctor", "--root", str(target))
    assert code == 0
    assert doc["schema"] == "forge/InstallationHealth/v1"
    assert {c["id"] for c in doc["checks"]} >= {"ledger", "mcp-config"}


def test_repair_restores_missing_mcp(target: Path) -> None:
    _invoke("--root", str(target), "--yes")
    mcp = target / ".mcp.json"
    doc = json.loads(mcp.read_text())
    doc["mcpServers"].pop("forge-doctor-api")
    doc["mcpServers"]["mine"] = {"command": "y"}
    mcp.write_text(json.dumps(doc))
    code, out = _invoke("repair", "--root", str(target))
    assert code == 0
    assert ".mcp.json" in out["repaired"]
    new = json.loads(mcp.read_text())
    assert new["mcpServers"]["forge-doctor-api"]["command"] == "forge-doctor-api"
    assert new["mcpServers"]["mine"] == {"command": "y"}


def test_uninstall_removes_owned_and_purges(target: Path) -> None:
    _invoke("--root", str(target), "--yes")
    code, doc = _invoke("uninstall", "--root", str(target), "--purge")
    assert code == 0
    assert doc["status"] == "completed"
    assert not (target / ".mcp.json").exists()
    assert not (target / "AGENTS.md").exists()
    assert not (target / ".forge-doctor-api").exists()


def test_uninstall_dry_run_is_a_plan(target: Path) -> None:
    _invoke("--root", str(target), "--yes")
    code, doc = _invoke("uninstall", "--root", str(target), "--dry-run")
    assert code == 0
    assert doc["status"] == "planned"
    assert (target / ".mcp.json").exists()


def test_update_latest_refused(target: Path) -> None:
    code, doc = _invoke("update", "--to", "latest")
    assert code == 1
    assert doc["verification"]["status"] == "FAIL"


def test_mcp_verify_emits_health_doc(target: Path) -> None:
    code, doc = _invoke("mcp-verify")
    assert doc["schema"] == "forge/InstallationHealth/v1"
    check = doc["checks"][0]
    assert check["id"] == "mcp-handshake"
    assert check["status"] in ("PASS", "FAIL", "BLOCKED", "UNVERIFIED")
    assert code == (1 if check["status"] == "FAIL" else 0)


def test_module_invocation_is_the_catalog_argv(tmp_path: Path) -> None:
    """``{python} -m forge_doctor_api install ...`` — the exact argv the
    forge-cli catalog should delegate to (documented in
    docs/installation/portable-installation.md)."""
    root = tmp_path / "consumer"
    root.mkdir()
    (root / ".git").mkdir()
    env = dict(os.environ)
    env["FORGE_HOME_OVERRIDE"] = str(tmp_path / "home")
    proc = subprocess.run(
        [
            sys.executable, "-m", "forge_doctor_api",
            "install", "--root", str(root), "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["status"] == "planned"
    assert doc["schema"] == "forge/InstallReceipt/v1"
