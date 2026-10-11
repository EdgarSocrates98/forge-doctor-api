#!/usr/bin/env python3
"""Forge Doctor API — AI host observation + launch (checkout-level).

Sibling of ``forge_install.py``: kept outside ``src/`` because the package
boundary (``tests/test_boundary.py``) bans ``subprocess``/``shutil``/``os``
imports — host interaction is a side-effecting concern of the checkout,
never of the Doctor engine. Same receipt contract as the sibling forges:

1. detect the binary (``shutil.which``);
2. read the version (``<bin> --version``);
3. check authentication through the official status subcommand — the
   receipt carries only the ``logged_in`` boolean, never the output (it
   can list credential paths);
4. read the repo's integration state (``forge_install.py status``);
5. with ``--launch`` and a TTY, run ``<bin>`` in the repo directory —
   the host inherits the terminal and returns its exit code.

    python scripts/forge_hosts.py [all|claude|devin|codex|copilot]
        [--root DIR] [--launch]

A signed-out host is never launched: the receipt points at the official
login command. Exit code: 0 observed/launched, 2 unknown host.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_TIMEOUT_S = 15
_OUT_MAX = 400

LOGIN_HINTS = {
    "devin": "devin auth login",
    "claude": "claude auth login",
    "codex": "codex login",
}

#: ``copilot`` has no documented status subcommand — ``logged_in`` stays
#: ``None`` (honest unknown).
HOST_NAMES: tuple[str, ...] = ("claude", "devin", "codex", "copilot")

_HOST_CMDS = {
    "claude": ("claude", ("auth", "status")),
    "devin": ("devin", ("auth", "status")),
    "codex": ("codex", ("login", "status")),
    "copilot": ("copilot", None),
}


def _runner(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=_TIMEOUT_S,
        errors="replace", check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _logged_in(host: str, out: str) -> bool | None:
    """Only the boolean. No legible positive/negative evidence -> ``None``."""
    if host == "claude":
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if isinstance(data, dict) and "loggedIn" in data:
            return bool(data["loggedIn"])
    low = out.lower()
    if any(s in low for s in (
        "not logged", "logged out", "no credentials", "unauthorized",
    )):
        return False
    if "logged in" in low:
        return True
    return None


def _call(executable: str, argv: list[str]) -> tuple[int, str] | dict[str, Any]:
    try:
        return _runner([executable, *argv])
    except subprocess.TimeoutExpired as exc:
        return {"status": "refused", "reason": "host_cli_timeout",
                "command": " ".join(argv), "timeout_s": exc.timeout}
    except OSError as exc:
        return {"status": "refused", "reason": "host_cli_failed",
                "command": " ".join(argv), "output": str(exc)[-_OUT_MAX:]}


def _integration(repo: Path) -> dict[str, Any]:
    """Install state via ``forge_install.py status`` — ``unverified`` when absent."""
    script = Path(__file__).resolve().parent / "forge_install.py"
    if not script.is_file():
        return {"state": "unknown", "error": "forge_install.py not found"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "status", "--root", str(repo)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        st = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"state": "unknown", "error": str(exc)[:200]}
    drift = st.get("drift") or {}
    return {
        "state": st.get("status", "unknown"),
        "drift": {
            "ok": drift.get("ok", 0),
            "modified": len(drift.get("modified") or []),
            "missing": len(drift.get("missing") or []),
        },
    }


def host_state(host: str, repo: Path) -> dict[str, Any]:
    if host not in _HOST_CMDS:
        return {"host": host, "state": "refused",
                "reason": "host_unknown", "known": list(_HOST_CMDS)}
    binary, auth_status = _HOST_CMDS[host]
    state: dict[str, Any] = {
        "host": host, "binary": binary, "launch_command": binary,
    }
    path = shutil.which(binary)
    if not path:
        state["state"] = "NOT_DETECTED"
        return state
    state["binary_path"] = path
    state["state"] = "DETECTED"

    version = _call(path, ["--version"])
    if isinstance(version, dict):
        state["version_refused"] = version
    else:
        rc, out = version
        first = next(
            (line.strip() for line in out.splitlines() if line.strip()), "")
        state["version"] = first or None
        state["state"] = "SUPPORTED" if rc == 0 else "DETECTED"

    if auth_status is None:
        state["logged_in"] = None
        state["auth_note"] = "no documented status subcommand in this revision"
    else:
        auth = _call(path, list(auth_status))
        if isinstance(auth, dict):
            state["auth_refused"] = auth
            state["logged_in"] = None
        else:
            state["logged_in"] = _logged_in(host, auth[1])
    if state.get("logged_in") is False:
        state["login_hint"] = LOGIN_HINTS.get(host)

    state["integration"] = _integration(repo)
    if state["logged_in"] is False:
        state["state"] = "NEEDS_LOGIN"
    else:
        integ = state["integration"].get("state")
        state["state"] = (
            "READY" if integ == "healthy"
            else f"INTEGRATION_{integ.upper()}" if integ in {"degraded", "broken"}
            else "SUPPORTED"
        )
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", nargs="?", default="all")
    parser.add_argument("--root", default=".")
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()

    if args.target not in (*HOST_NAMES, "all"):
        print(json.dumps({
            "status": "refused", "reason": "host_unknown",
            "host": args.target, "known": [*HOST_NAMES, "all"],
        }, indent=2))
        return 2

    repo = Path(args.root)
    names = list(HOST_NAMES) if args.target == "all" else [args.target]
    states = [host_state(n, repo) for n in names]
    receipt: dict[str, Any] = {
        "repo": repo.as_posix(), "hosts": states, "launched": False,
    }
    if args.target == "all" or not args.launch:
        if args.launch:
            receipt["launch_refused"] = (
                "selector `all` does not launch: pick one host"
            )
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
        return 0

    state = states[0]
    if state["state"] == "NOT_DETECTED":
        receipt["launch_refused"] = "host_absent"
    elif state["state"] == "NEEDS_LOGIN":
        receipt["launch_refused"] = "login_required"
        receipt["login_hint"] = state.get("login_hint")
    elif not sys.stdin.isatty():
        receipt["launch_refused"] = "no_tty"
    else:
        # Path came from shutil.which — same trust level as any PATH exec.
        receipt["launched"] = True
        receipt["host_exit_code"] = subprocess.call(
            [state["binary_path"]], cwd=str(repo))
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return int(receipt.get("host_exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
