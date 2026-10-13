"""``scripts/forge_hosts.py`` — the checkout-level host observe/launch flow.

Subprocess-level tests run the real script (same contract as
``test_forge_install.py``); launch-path tests load the module and inject
``which``/runner seams so no real binary is ever touched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "forge_hosts.py"


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=e, timeout=60)


def _json(proc: subprocess.CompletedProcess) -> dict:
    assert proc.stdout.strip(), proc.stderr
    return json.loads(proc.stdout)


def _empty_path() -> dict:
    return {"PATH": os.devnull}


def _load(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("forge_hosts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_integration", lambda _r: {"state": "healthy",
                                                       "drift": {"ok": 1,
                                                                 "modified": 0,
                                                                 "missing": 0}})
    return mod


# --- subprocess level (real script, real filesystem) -------------------------

def test_all_hosts_observed_and_never_launch(tmp_path: Path) -> None:
    proc = _run("--root", str(tmp_path), env=_empty_path())
    assert proc.returncode == 0, proc.stderr
    doc = _json(proc)
    assert doc["launched"] is False
    assert [h["host"] for h in doc["hosts"]] == ["claude", "devin",
                                               "codex", "copilot"]
    assert all(h["state"] == "NOT_DETECTED" for h in doc["hosts"])


def test_unknown_host_refuses_exit2() -> None:
    proc = _run("generic", env=_empty_path())
    assert proc.returncode == 2
    assert _json(proc)["reason"] == "host_unknown"


def test_launch_absent_host_refuses(tmp_path: Path) -> None:
    proc = _run("devin", "--root", str(tmp_path), "--launch",
                env=_empty_path())
    doc = _json(proc)
    assert doc["launched"] is False
    assert doc["launch_refused"] == "host_absent"


def test_all_selector_refuses_launch(tmp_path: Path) -> None:
    proc = _run("all", "--root", str(tmp_path), "--launch",
                env=_empty_path())
    doc = _json(proc)
    assert doc["launched"] is False
    assert "selector" in doc["launch_refused"]


# --- module level (injected seams — never a real binary) ---------------------

def _fake(mod, outputs, present):
    monkey_shim = lambda name: present.get(name)  # noqa: E731

    def run(argv):
        key = tuple(argv[1:])
        assert key in outputs, f"unexpected argv: {argv}"
        return outputs[key]
    return monkey_shim, run


def test_ready_state_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load(monkeypatch)
    outputs = {
        ("--version",): (0, "devin 3000.11.3 (abc)\n"),
        ("auth", "status"): (0, "Logged in (via Devin).\nFile: /x/secret.toml"),
    }
    which, run = _fake(mod, outputs, {"devin": "/bin/devin"})
    monkeypatch.setattr(mod.shutil, "which", which)
    monkeypatch.setattr(mod, "_runner", run)
    state = mod.host_state("devin", tmp_path)
    assert state["state"] == "READY"
    assert state["version"] == "devin 3000.11.3 (abc)"
    assert state["logged_in"] is True
    assert "secret" not in json.dumps(state)


def test_signed_out_never_launches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                   capsys) -> None:
    mod = _load(monkeypatch)
    outputs = {
        ("--version",): (0, "codex-cli 0.160.0"),
        ("login", "status"): (0, "Not logged in"),
    }
    which, run = _fake(mod, outputs, {"codex": "/bin/codex"})
    monkeypatch.setattr(mod.shutil, "which", which)
    monkeypatch.setattr(mod, "_runner", run)
    launched = []
    monkeypatch.setattr(mod.subprocess, "call",
                        lambda *a, **k: launched.append(True))
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys, "argv", ["forge_hosts.py", "codex",
                                    "--root", str(tmp_path), "--launch"])
    rc = mod.main()
    doc = json.loads(capsys.readouterr().out)
    assert launched == []
    assert doc["launched"] is False
    assert doc["launch_refused"] == "login_required"
    assert doc["login_hint"] == "codex login"
    assert doc["hosts"][0]["state"] == "NEEDS_LOGIN"
    assert rc == 0


def test_no_tty_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                        capsys) -> None:
    mod = _load(monkeypatch)
    outputs = {
        ("--version",): (0, "2.1.295 (Claude Code)"),
        ("auth", "status"): (0, json.dumps({"loggedIn": True})),
    }
    which, run = _fake(mod, outputs, {"claude": "/bin/claude"})
    monkeypatch.setattr(mod.shutil, "which", which)
    monkeypatch.setattr(mod, "_runner", run)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys, "argv", ["forge_hosts.py", "claude",
                                    "--root", str(tmp_path), "--launch"])
    mod.main()
    doc = json.loads(capsys.readouterr().out)
    assert doc["launched"] is False
    assert doc["launch_refused"] == "no_tty"
    assert doc["hosts"][0]["launch_command"] == "claude"


def test_tty_launch_records_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 capsys) -> None:
    mod = _load(monkeypatch)
    outputs = {
        ("--version",): (0, "devin 3000.11.3 (abc)"),
        ("auth", "status"): (0, "Logged in (via Devin)."),
    }
    which, run = _fake(mod, outputs, {"devin": "/bin/devin"})
    monkeypatch.setattr(mod.shutil, "which", which)
    monkeypatch.setattr(mod, "_runner", run)
    calls = []
    monkeypatch.setattr(mod.subprocess, "call",
                        lambda argv, cwd: calls.append((argv, cwd)) or 0)
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys, "argv", ["forge_hosts.py", "devin",
                                    "--root", str(tmp_path), "--launch"])
    rc = mod.main()
    doc = json.loads(capsys.readouterr().out)
    assert doc["launched"] is True
    assert doc["host_exit_code"] == 0
    assert calls == [(["/bin/devin"], str(tmp_path))]
    assert rc == 0


def test_copilot_auth_honest_unknown(tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load(monkeypatch)
    which, run = _fake(mod, {("--version",): (0, "copilot 1.0")},
                       {"copilot": "/bin/copilot"})
    monkeypatch.setattr(mod.shutil, "which", which)
    monkeypatch.setattr(mod, "_runner", run)
    state = mod.host_state("copilot", tmp_path)
    assert state["logged_in"] is None
    assert "auth_note" in state
