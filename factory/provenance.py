"""Spec 089 — provenance.json generator (in-toto-lite).

Emits a deterministic provenance document for the release artifact
set: builder identity (local/CI), source repository + revision, the
build commands that produced `dist/`, per-artifact sha256 digests, and
the tool versions used. Deterministic ordering — same tree, same
document (digests follow the artifacts).

`builder.id` resolves: `GITHUB_ACTIONS` env →
`https://github.com/<repo>/actions/runs/<run_id>`; else `local-build`.
No timestamps — provenance is reproducible, not a log.

Run:  python factory/provenance.py [--stdout] [--dist-dir dist]
      [--out factory/artifacts/provenance.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ARTIFACT = ROOT / "factory" / "artifacts" / "provenance.json"
DIST = ROOT / "dist"

BUILD_COMMANDS = ("python -m build",)


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True,
            timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    val = out.stdout.strip()
    return val if out.returncode == 0 and val else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _builder_id() -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run = os.environ.get("GITHUB_RUN_ID", "")
        if repo and run:
            return f"https://github.com/{repo}/actions/runs/{run}"
        return "github-actions"
    return "local-build"


def _tool_version() -> str:
    init = (SRC / "forge_doctor_api" / "__init__.py").read_text(
        encoding="utf-8")
    import re
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    return m.group(1) if m else "unknown"


def build_provenance(*, dist_dir: Path = DIST) -> dict:
    repo = _git("config", "--get", "remote.origin.url") or "(local)"
    revision = _git("rev-parse", "HEAD") or "(unknown)"
    subjects = [
        {"name": p.name, "digest": {"sha256": _sha256(p)}}
        for p in sorted(dist_dir.iterdir())
        if p.is_file() and p.suffix in {".whl", ".gz"}
    ] if dist_dir.is_dir() else []
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://forge-doctor.dev/provenance/v1",
        "subject": subjects,
        "predicate": {
            "builder": {"id": _builder_id()},
            "source": {"repo": repo, "revision": revision},
            "build": {"commands": list(BUILD_COMMANDS)},
            "tools": {
                "forge_doctor_api": _tool_version(),
                "python": platform.python_version(),
            },
        },
    }


def _render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ARTIFACT)
    parser.add_argument("--dist-dir", type=Path, default=DIST)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()
    rendered = _render(build_provenance(dist_dir=args.dist_dir))
    if args.stdout:
        sys.stdout.write(rendered)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    data = json.loads(rendered)
    print(f"provenance: {args.out} "
          f"({len(data['subject'])} subjects, "
          f"builder={data['predicate']['builder']['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
