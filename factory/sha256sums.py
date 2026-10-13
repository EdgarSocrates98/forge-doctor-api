"""Spec 080 — deterministic SHA256SUMS for release artifacts.

Two modes:

  python factory/sha256sums.py            hash every file in dist/
                                          (wheel, sdist, sbom …) and
                                          write dist/SHA256SUMS sorted
                                          by filename
  python factory/sha256sums.py --verify   re-hash dist/ and diff against
                                          the recorded dist/SHA256SUMS;
                                          exits non-zero on drift or a
                                          missing artifact

`SHA256SUMS` itself is excluded from the manifest. Hashes cover bytes
on disk — the same artifact rebuilt later may differ (zip timestamps),
so the recorded file travels with the artifacts it describes.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
SUMS = "SHA256SUMS"


def _hashes(dist: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for artifact in sorted(dist.iterdir()):
        if artifact.name == SUMS or not artifact.is_file():
            continue
        entries[artifact.name] = hashlib.sha256(
            artifact.read_bytes()).hexdigest()
    return entries


def _render(entries: dict[str, str]) -> str:
    return "".join(f"{digest}  {name}\n"
                   for name, digest in sorted(entries.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true",
                        help="re-hash dist/ and diff against the "
                             "recorded SHA256SUMS")
    parser.add_argument("--dist", type=Path, default=DIST)
    args = parser.parse_args()
    dist = args.dist
    if not dist.is_dir():
        print(f"sha256sums: {dist} does not exist — run "
              f"`python -m build` first", file=sys.stderr)
        return 1
    actual = _hashes(dist)
    if not actual:
        print(f"sha256sums: {dist} contains no artifacts",
              file=sys.stderr)
        return 1
    sums_path = dist / SUMS
    if args.verify:
        if not sums_path.exists():
            print(f"sha256sums --verify: {sums_path} missing — run "
                  f"`python factory/sha256sums.py` to record it",
                  file=sys.stderr)
            return 1
        recorded: dict[str, str] = {}
        for line in sums_path.read_text(
                encoding="utf-8").splitlines():
            digest, _, name = line.partition("  ")
            if digest and name:
                recorded[name.strip()] = digest
        if recorded != actual:
            print(f"sha256sums --verify: drift —\n"
                  f"recorded: {_render(recorded)}"
                  f"actual:   {_render(actual)}",
                  file=sys.stderr)
            return 1
        print(f"sha256sums --verify: {len(actual)} artifact(s) "
              f"match {sums_path}")
        return 0
    sums_path.write_text(_render(actual), encoding="utf-8")
    print(f"sha256sums: {sums_path} ({len(actual)} artifacts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
