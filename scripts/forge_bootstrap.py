#!/usr/bin/env python3
"""Forge bootstrap — clone once, setup once, install anywhere.

Canonical source: ``the-forge/scripts/installkit/forge_bootstrap.py``.
Vendored per-Forge at ``scripts/forge_bootstrap.py``; driven by the
repo-local ``forge.json`` so the file itself is identical everywhere.

Pipeline (governed — see docs/portable-installation/):

    discover → resolve-python → create-venv → install-runtime
    → write-launcher → register → smoke-verify → report

stdlib-only, no network access beyond the explicit ``pip install`` step,
no credential reads, never touches the project's own venv.

Usage (from repo root, via setup.sh/setup.ps1 or directly):

    python scripts/forge_bootstrap.py [--repo .] [--dry-run]
        [--install-dir DIR] [--no-launcher] [--allow-download]
        [--python EXE] [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

_BOOTSTRAP_VERSION = "1.0.0"
SCHEMA_MANIFEST = "forge/InstallationManifest/v1"
SCHEMA_RECEIPT = "forge/InstallReceipt/v1"
FORGE_HOME = ".forge"
INSTALLATIONS = "installations"
INSTALLS = "installs"


class Refusal(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def _log(msg: str) -> None:
    print(f"[forge-bootstrap] {msg}", flush=True)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _home() -> Path:
    return Path(os.environ.get("FORGE_HOME_OVERRIDE") or Path.home())


def forge_home() -> Path:
    return _home() / FORGE_HOME


def shim_dir() -> Path:
    return _home() / ".local" / "bin"


def _venv_python(v: Path) -> Path:
    return v / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_bin(v: Path) -> Path:
    return v / ("Scripts" if os.name == "nt" else "bin")


def _run(cmd: list[str], timeout: int = 300, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, **kw)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(repo: Path) -> dict[str, Any]:
    """``forge.json`` at the repo root is the declarative driver."""
    cfg_path = repo / "forge.json"
    if not cfg_path.exists():
        raise Refusal("FORGE-INSTALL-NO-CONFIG",
                      f"{cfg_path} missing — run inside a Forge checkout")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Refusal("FORGE-INSTALL-BAD-CONFIG", f"forge.json: {exc}")
    required = ("forge_id", "package", "distribution", "cli", "python")
    missing = [k for k in required if k not in cfg]
    if missing:
        raise Refusal("FORGE-INSTALL-BAD-CONFIG",
                      f"forge.json missing keys: {missing}")
    return cfg


# --------------------------------------------------------------------------
# Stage 1-2: discover environment + resolve a compatible python
# --------------------------------------------------------------------------

def _semver_tuple(s: str) -> tuple[int, int, int]:
    parts = s.split(".")[:3]
    return tuple(int(p) for p in parts) if len(parts) == 3 else (0, 0, 0)


def _satisfies(version: str, spec: str) -> bool:
    """Tiny specifier check: comma-separated >=,>,<,<=,==,!= clauses."""
    v = _semver_tuple(version)
    for clause in spec.split(","):
        clause = clause.strip()
        for op in (">=", "<=", "!=", "==", ">", "<"):
            if clause.startswith(op):
                tgt = _semver_tuple(clause[len(op):])
                if op == ">=" and not v >= tgt: return False
                if op == "<=" and not v <= tgt: return False
                if op == ">" and not v > tgt:  return False
                if op == "<" and not v < tgt:  return False
                if op == "==" and not v == tgt: return False
                if op == "!=" and not v != tgt: return False
                break
    return True


def _python_version(exe: str) -> str | None:
    try:
        r = _run([exe, "-c",
                  "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"],
                 timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def find_python(spec: str, explicit: str | None,
                allow_download: bool, log) -> str:
    """Return a python executable satisfying ``spec``. Prefers interpreters
    already on PATH; ``uv`` (which can fetch a pinned interpreter) is used
    only with --allow-download."""
    if explicit:
        v = _python_version(explicit)
        if not v or not _satisfies(v, spec):
            raise Refusal("FORGE-INSTALL-PYTHON-INCOMPATIBLE",
                          f"--python {explicit}: {v or 'unusable'} does not satisfy {spec}")
        return explicit

    candidates: list[str] = []
    if os.name == "nt":
        for minor in range(9, 15):
            candidates.append(f"py -3.{minor}")
        candidates += ["python", "python3"]
    else:
        for minor in range(9, 15):
            candidates.append(f"python3.{minor}")
        candidates += ["python3", "python"]

    for cand in candidates:
        exe = shutil.which(cand.split()[0])
        if not exe:
            continue
        if cand.startswith("py "):
            cmd = cand.split() + ["-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"]
        else:
            cmd = [cand, "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"]
        try:
            r = _run(cmd, timeout=15)
            v = r.stdout.strip()
            if r.returncode == 0 and _satisfies(v, spec):
                log(f"python {v} via {cand!r} satisfies {spec}")
                # resolve the real exe (the `py` launcher loses the minor pin)
                rr = _run(cmd[:-1] + ["-c", "import sys;print(sys.executable)"],
                          timeout=15)
                return rr.stdout.strip() if rr.returncode == 0 and rr.stdout.strip() else exe
        except (OSError, subprocess.TimeoutExpired):
            continue

    # uv can resolve a pinned interpreter; opt-in only (network download).
    uv = shutil.which("uv")
    if uv and allow_download:
        wanted = spec.split(",")[0].lstrip(">=<")
        minor = ".".join(wanted.split(".")[:2]) or "3.12"
        log(f"no local python satisfies {spec}; `uv python install {minor}`")
        r = _run(["uv", "python", "install", minor], timeout=600)
        if r.returncode != 0:
            raise Refusal("FORGE-INSTALL-PYTHON-INCOMPATIBLE",
                          f"uv could not provide python {minor}: {r.stderr.strip()}")
        r = _run(["uv", "python", "find", minor], timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()

    raise Refusal("FORGE-INSTALL-PYTHON-INCOMPATIBLE",
                  f"no interpreter on PATH satisfies {spec}; install one or "
                  "re-run with --allow-download to let uv fetch it")


# --------------------------------------------------------------------------
# Stage 3-4: isolated venv + install
# --------------------------------------------------------------------------

def create_venv(root: Path, python: str, log) -> Path:
    venv_dir = root / "venv"
    if venv_dir.exists() and _venv_python(venv_dir).exists():
        log(f"reusing venv {venv_dir}")
        return venv_dir
    log(f"creating venv {venv_dir} with {python}")
    builder = venv.EnvBuilder(with_pip=True, upgrade_deps=False)
    if os.path.basename(python) not in ("python", "python3"):
        # explicit exe — delegate to it for venv creation
        r = _run([python, "-m", "venv", str(venv_dir)], timeout=300)
        if r.returncode != 0:
            raise Refusal("FORGE-INSTALL-VENV-FAILED", r.stderr.strip()[:400])
    else:
        builder.create(str(venv_dir))
    if not _venv_python(venv_dir).exists():
        raise Refusal("FORGE-INSTALL-VENV-FAILED", f"{venv_dir} incomplete")
    return venv_dir


def install_package(repo: Path, venv: Path, extras: list[str],
                    editable: bool, allow_download: bool, log) -> None:
    """Install the forge from the checkout. Prefers a built wheel (no repo
    dependence after install); falls back to ``pip install`` which may hit
    the network for deps — allowed and reported, never silent."""
    pip = [str(_venv_python(venv)), "-m", "pip"]
    # Build a wheel first so the installed artifact is immutable.
    log("building wheel from checkout")
    r = _run(pip + ["wheel", str(repo), "-w", str(repo / ".forge-wheels"),
                    "--no-deps"], timeout=600)
    whl = None
    whl_dir = repo / ".forge-wheels"
    if r.returncode == 0 and whl_dir.is_dir():
        wheels = sorted(whl_dir.glob("*.whl"))
        whl = wheels[-1] if wheels else None
    target = str(whl) if whl else str(repo)
    if whl:
        log(f"installing wheel {whl.name}")
    else:
        log("wheel build unavailable; installing from checkout "
            f"(deps may resolve over network)")
    req = target if not extras else f"{target}[{','.join(extras)}]"
    cmd = pip + ["install", "--upgrade"]
    if editable:
        cmd.append("-e")
    cmd.append(req if not editable else str(repo))
    r = _run(cmd, timeout=900)
    if r.returncode != 0:
        offline_hint = "" if allow_download else (
            " — retry with --allow-download if deps are missing")
        raise Refusal("FORGE-INSTALL-RUNTIME-FAILED",
                      f"pip install failed{offline_hint}: {r.stderr.strip()[-400:]}")
    shutil.rmtree(whl_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# Stage 5-7: launcher, registry, smoke
# --------------------------------------------------------------------------

def write_launcher(cli: str, venv: Path, no_launcher: bool, log) -> Path | None:
    if no_launcher:
        return None
    bindir = _venv_bin(venv)
    real = bindir / (cli + (".exe" if os.name == "nt" else ""))
    if not real.exists():
        real = bindir / cli
    if not real.exists():
        raise Refusal("FORGE-INSTALL-CLI-MISSING",
                      f"{cli} not in {bindir} — package script entry missing?")
    d = shim_dir()
    d.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (d / f"{cli}.cmd").write_text(f'@echo off\r\n"{real}" %*\r\n')
        (d / cli).write_text(f'#!/bin/sh\nexec "{real}" "$@"\n')
        path = d / f"{cli}.cmd"
    else:
        path = d / cli
        path.write_text(f'#!/bin/sh\nexec "{real}" "$@"\n')
        path.chmod(0o755)
    log(f"launcher {path}")
    return path


def register(cfg: dict, install_root: Path, venv: Path, version: str,
             source: dict, shim: Path | None, mcp_cmd: list[str],
             mcp_name: str | None, hosts: dict) -> Path:
    doc = {
        "schema": SCHEMA_MANIFEST,
        "forge_id": cfg["forge_id"], "package": cfg["package"],
        "distribution": cfg["distribution"],
        "cli": {"name": cfg["cli"],
                "version_cmd": [cfg["cli"], "--version"]},
        "version": version,
        "install_root": str(install_root),
        "venv": str(venv),
        "python": {"executable": str(_venv_python(venv)),
                   "version": platform.python_version(),
                   "satisfies": cfg["python"]},
        "source": source,
        "installed_at": _now(), "updated_at": _now(),
        "installed_by": {"agent": "forge_bootstrap",
                         "version": _BOOTSTRAP_VERSION},
        "hosts": hosts,
    }
    if shim:
        doc["cli"]["shim"] = str(shim)
    if mcp_name:
        doc["mcp"] = {"server_name": mcp_name, "command": mcp_cmd,
                      "verified": False}
    if cfg.get("install_command"):
        # Alternate install entrypoint (argv template; {python}/{checkout}
        # resolved by the delegator) for forges whose package boundary
        # forbids an in-package install engine.
        doc["install_command"] = list(cfg["install_command"])
    path = forge_home() / INSTALLATIONS / f"{cfg['forge_id']}.json"
    _atomic_write(path, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
    _log(f"registered {path}")
    return path


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def detect_hosts() -> dict[str, Any]:
    """Observe only — which host CLIs/dirs exist; never probes live."""
    out: dict[str, Any] = {}
    for host, exe in (("claude", "claude"), ("devin", "devin"),
                      ("codex", "codex"), ("copilot", "copilot")):
        found = shutil.which(exe)
        dirs = {"claude": ["~/.claude"], "devin": ["~/.devin", "~/.agents"],
                "codex": ["~/.codex", "~/.agents"],
                "copilot": ["~/.agents"]}[host]
        dir_found = [d for d in dirs
                     if Path(os.path.expanduser(d)).exists()]
        out[host] = {"cli": bool(found), "cli_path": found,
                     "config_dirs": dir_found,
                     "activatable": bool(found or dir_found)}
    return out


def smoke(cli: str, venv: Path, version_cmd: list[str], log) -> dict[str, str]:
    exe = _venv_bin(venv) / (cli + (".exe" if os.name == "nt" else ""))
    if not exe.exists():
        exe = _venv_bin(venv) / cli
    try:
        r = _run([str(exe)] + version_cmd, timeout=30)
        ok = r.returncode == 0
        ver = r.stdout.strip().splitlines()[0] if ok else ""
        log(f"smoke `{cli} {' '.join(version_cmd)}` -> {ver or r.returncode}")
        return {"status": "PASS" if ok else "FAIL", "version": ver}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "FAIL", "detail": str(exc)}


def write_receipt(cfg: dict, receipt: dict) -> Path:
    path = (forge_home() / INSTALLATIONS /
            f".{cfg['forge_id']}-bootstrap.json")
    _atomic_write(path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    return path


# --------------------------------------------------------------------------
# orchestrate
# --------------------------------------------------------------------------

def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="forge checkout root")
    ap.add_argument("--install-dir", default=None,
                    help="override ~/.forge/installs/<forge_id>")
    ap.add_argument("--python", default=None)
    ap.add_argument("--editable", action="store_true",
                    help="pip install -e (dev mode; ties CLI to checkout)")
    ap.add_argument("--extras", default="", help="comma-separated extras")
    ap.add_argument("--no-launcher", action="store_true")
    ap.add_argument("--allow-download", action="store_true",
                    help="let uv fetch a pinned python; pip may use network")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    def log(m: str) -> None:
        if not args.quiet:
            _log(m)

    repo = Path(args.repo).resolve()
    try:
        cfg = load_config(repo)
    except Refusal as exc:
        print(json.dumps({"status": "failed",
                          "error": {"kind": exc.kind, "detail": exc.detail}},
                         indent=2))
        return 2

    extras = [e.strip() for e in args.extras.split(",") if e.strip()] \
        or cfg.get("extras", [])
    install_root = Path(args.install_dir) if args.install_dir else \
        forge_home() / INSTALLS / cfg["forge_id"]
    source = {"kind": "git-checkout", "path": str(repo),
              "ref": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
              "rev": _git(repo, "rev-parse", "HEAD"),
              "editable": bool(args.editable)}

    report = {
        "schema": SCHEMA_RECEIPT, "forge_id": cfg["forge_id"],
        "operation": "install", "scope": "user",
        "target_root": str(install_root),
        "platform": {"os": platform.system(), "arch": platform.machine(),
                     "python": platform.python_version()},
        "stages": [], "status": "failed", "created_at": _now(),
    }

    def stage(name: str, fn) -> Any:
        if args.dry_run:
            report["stages"].append({"stage": name, "status": "planned"})
            return None
        try:
            out = fn()
            report["stages"].append({"stage": name, "status": "done"})
            return out
        except Refusal as exc:
            report["stages"].append({"stage": name, "status": "refused",
                                     "kind": exc.kind, "detail": exc.detail})
            raise

    try:
        hosts = detect_hosts()
        report["hosts_detected"] = hosts
        python = stage("resolve-python", lambda: find_python(
            cfg["python"], args.python, args.allow_download, log))
        venv_dir = stage("create-venv",
                         lambda: create_venv(install_root, python, log))
        stage("install-runtime", lambda: install_package(
            repo, venv_dir, extras, args.editable,
            args.allow_download, log))
        shim = stage("write-launcher", lambda: write_launcher(
            cfg["cli"], venv_dir, args.no_launcher, log))
        sm = stage("smoke", lambda: smoke(
            cfg["cli"], venv_dir, ["--version"], log))
        version = (sm or {}).get("version", cfg.get("version", "0.0.0"))
        stage("register", lambda: register(
            cfg, install_root, venv_dir, version, source, shim,
            cfg.get("mcp_command", []), cfg.get("mcp_server_name"), hosts))
        if sm and sm.get("status") != "PASS":
            raise Refusal("FORGE-INSTALL-VERIFY-FAILED",
                          f"smoke failed: {sm}")
        report["status"] = "planned" if args.dry_run else "completed"
        report["cli"] = cfg["cli"]
        report["shim_dir"] = str(shim_dir())
        report["install_root"] = str(install_root)
        guide = _path_guidance()
        if guide:
            report["path_guidance"] = guide
            log(f"NOTE: {guide}")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except Refusal as exc:
        report["error"] = {"kind": exc.kind, "detail": exc.detail}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    finally:
        if not args.dry_run:
            write_receipt(cfg, report)


def _git(repo: Path, *a) -> str | None:
    try:
        r = _run(["git", "-C", str(repo), *a], timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except OSError:
        return None


def _path_guidance() -> str | None:
    d = str(shim_dir())
    if d in os.environ.get("PATH", "").split(os.pathsep):
        return None
    if os.name == "nt":
        return f'setx PATH "%PATH%;{d}"  # open a new terminal after'
    sh = Path(os.environ.get("SHELL", "/bin/sh")).name
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}.get(sh, "~/.profile")
    return f'echo \'export PATH="{d}:$PATH"\' >> {rc}  # restart the shell'


if __name__ == "__main__":
    raise SystemExit(run())
