"""Spec 089 — release smoke against the built wheel.

Proves the *artifact* works, not the source tree: creates a clean venv,
installs the wheel, then exercises the shipped CLI end-to-end —
`--version`, `--help`, `scan`, `contract inspect`, `lab --no-record`,
and the MCP stdio handshake (via `factory/mcp_smoke.py`) when the `mcp`
extra is installed.

Run:  python factory/release_smoke.py [--wheel dist/x.whl]
      [--extras "[graphql,mcp]"] [--no-lab] [--venv PATH]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "labs" / "golden" / "fastapi-service"
MCP_SMOKE = ROOT / "factory" / "mcp_smoke.py"


def _venv_bin(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _run(cmd: list[str], label: str) -> str:
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise SystemExit(
            f"release_smoke: {label} failed ({proc.returncode})\n"
            f"{(proc.stderr or proc.stdout)[-2000:]}")
    return proc.stdout


def _wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit(
            f"release_smoke: no wheel in {dist_dir}; run "
            "`python -m build` first")
    return wheels[0]


def smoke(*, wheel: Path, extras: str, run_lab: bool,
          keep_venv: Path | None) -> None:
    tmp = tempfile.TemporaryDirectory()
    venv_dir = keep_venv or Path(tmp.name) / "venv"
    if not keep_venv or not (venv_dir / "pyvenv.cfg").is_file():
        print(f"release_smoke: venv {venv_dir}")
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    bin_dir = _venv_bin(venv_dir)
    exe = bin_dir / ("forge-doctor-api.exe" if os.name == "nt"
                     else "forge-doctor-api")
    py = bin_dir / ("python.exe" if os.name == "nt" else "python")

    print(f"release_smoke: install {wheel.name}{extras}")
    _run([str(py), "-m", "pip", "install", "--quiet",
          f"{wheel}{extras}"], "pip install")

    print("release_smoke: --version / --help")
    _run([str(exe), "--version"], "--version")
    _run([str(exe), "--help"], "--help")

    print(f"release_smoke: scan {FIXTURE}")
    _run([str(exe), "scan", str(FIXTURE), "--format", "agent"], "scan")

    print("release_smoke: contract inspect")
    _run([str(exe), "contract", "inspect", str(FIXTURE)],
         "contract inspect")

    if run_lab:
        print("release_smoke: lab --no-record")
        _run([str(exe), "lab", "--no-record"], "lab")

    if "mcp" in extras:
        print("release_smoke: MCP stdio handshake")
        _run([sys.executable, str(MCP_SMOKE), "--exe", str(exe)],
             "mcp_smoke")

    tmp.cleanup()
    print("release_smoke: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=None)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--extras", default="")
    parser.add_argument("--no-lab", action="store_true",
                        help="skip the lab corpus leg")
    parser.add_argument("--venv", type=Path, default=None,
                        help="reuse/create a venv at PATH instead of a "
                             "tempdir (useful for debugging)")
    args = parser.parse_args()
    wheel = args.wheel or _wheel(args.dist_dir)
    smoke(wheel=wheel, extras=args.extras,
          run_lab=not args.no_lab, keep_venv=args.venv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
