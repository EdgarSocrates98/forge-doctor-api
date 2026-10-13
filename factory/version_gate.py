"""Spec 089 — version-consistency gate.

Fails when any version-bearing surface diverges:

- `pyproject.toml` `project.version`
- `src/forge_doctor_api/__init__.py` `__version__`
- `src/forge_doctor_api/sdk.py` `SDK_VERSION`
- `factory/artifacts/release-manifest.json` `version` (when present)
- `dist/*.whl` / `dist/*.tar.gz` filenames (when dist exists)

Exits 1 listing every divergence; prints the resolved version on pass.

Run:  python factory/version_gate.py [--dist-dir dist]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MANIFEST = ROOT / "factory" / "artifacts" / "release-manifest.json"

_WHEEL_RE = re.compile(r"^forge_doctor_api-([^-]+)-py3-none-any\.whl$")
_SDIST_RE = re.compile(r"^forge_doctor_api-(.+)\.tar\.gz$")


def _re_version(path: Path, pattern: str) -> str | None:
    m = re.search(pattern, path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def gather(dist_dir: Path) -> dict[str, str | None]:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    sources: dict[str, str | None] = {
        "pyproject": project.get("version"),
        "__init__.__version__": _re_version(
            SRC / "forge_doctor_api" / "__init__.py",
            r'__version__\s*=\s*"([^"]+)"'),
        "sdk.SDK_VERSION": _re_version(
            SRC / "forge_doctor_api" / "sdk.py",
            r'SDK_VERSION\s*=\s*"([^"]+)"'),
    }
    if MANIFEST.is_file():
        sources["release-manifest"] = json.loads(
            MANIFEST.read_text("utf-8")).get("version")
    if dist_dir.is_dir():
        for p in sorted(dist_dir.iterdir()):
            m = _WHEEL_RE.match(p.name) or _SDIST_RE.match(p.name)
            if m:
                sources[f"dist:{p.name}"] = m.group(1)
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path,
                        default=ROOT / "dist")
    args = parser.parse_args()
    sources = gather(args.dist_dir)
    canonical = sources["pyproject"]
    divergent = {
        k: v for k, v in sources.items() if v != canonical
    }
    missing = [k for k, v in sources.items() if v is None]
    if missing:
        print("version_gate: unresolvable version surfaces:",
              ", ".join(sorted(missing)), file=sys.stderr)
        return 1
    if divergent:
        print(f"version_gate: canonical={canonical} divergent:",
              file=sys.stderr)
        for k, v in sorted(divergent.items()):
            print(f"  {k} = {v}", file=sys.stderr)
        return 1
    print(f"version_gate: {canonical} consistent across "
          f"{len(sources)} surfaces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
