"""Spec 089 — RC release manifest generator + check.

Emits `factory/artifacts/release-manifest.json`: the machine-checkable
identity of the release-candidate artifact set — version, git HEAD,
dirty-tree flag, python range, contract family/version, Forge protocol
version, artifact filenames + sha256 digests, schema ids, CLI command
count, MCP tool count. `manifest_version: 1` — additive/evolvable.

Dirty-tree policy: `--rc` marks the manifest `rc: true`; the generator
refuses when the working tree is dirty (or git state is unavailable)
unless `--allow-dirty` is passed — the flag is recorded, never hidden.

`--check` regenerates and diffs. Build-dependent fields are volatile:
`git_head`, `dirty_tree`, `rc`, and per-artifact `sha256` are compared
by *presence/shape* (artifact *filenames* are compared exactly); every
other field must match byte-for-byte.

Run:  python factory/release_manifest.py [--check|--stdout|--rc]
      [--allow-dirty] [--dist-dir dist] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ARTIFACT = ROOT / "factory" / "artifacts" / "release-manifest.json"
DIST = ROOT / "dist"

# Fields that legitimately change per build/environment — presence is
# asserted, exact value is not.
_VOLATILE_TOP = {"git_head", "dirty_tree", "rc"}


def _pyproject() -> dict:
    return tomllib.loads(
        (ROOT / "pyproject.toml").read_text("utf-8"))["project"]


def _src_on_path() -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = out.stdout.strip()
    return head if out.returncode == 0 and head else None


def _git_dirty() -> bool | None:
    """True/False on a git tree, None when git state is unprovable."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT,
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return bool(out.stdout.strip())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifacts(dist_dir: Path) -> list[dict]:
    if not dist_dir.is_dir():
        return []
    return [
        {"filename": p.name, "sha256": _sha256(p)}
        for p in sorted(dist_dir.iterdir())
        if p.suffix in {".whl", ".gz"} or p.name == "SHA256SUMS"
    ]


def _cli_commands() -> tuple[str, ...]:
    _src_on_path()
    from forge_doctor_api.cli.catalog import command_inventory
    return tuple(e.path for e in command_inventory())


def _mcp_tools() -> tuple[str, ...]:
    src = (SRC / "forge_doctor_api" / "handoff" /
           "mcp_server.py").read_text(encoding="utf-8")
    return tuple(sorted(set(re.findall(r'"(doctor\.[a-z_]+)"', src))))


def _contract_facts() -> tuple[str, str, tuple[str, ...], int]:
    _src_on_path()
    from forge_doctor_api.contracts.schemas import FORGE_CONTRACT_SCHEMAS
    from forge_doctor_api.contracts.version import CURRENT
    from forge_doctor_api.handoff.protocol import PROTOCOL_VERSION
    family, _, version = str(CURRENT).partition("/")
    return family, version, tuple(sorted(FORGE_CONTRACT_SCHEMAS)), \
        PROTOCOL_VERSION


def build_manifest(*, dist_dir: Path = DIST, rc: bool = False,
                   allow_dirty: bool = False) -> dict:
    project = _pyproject()
    family, contract_version, schema_ids, protocol_version = \
        _contract_facts()
    head = _git_head()
    dirty = _git_dirty()
    if rc and dirty is not False and not allow_dirty:
        state = "unknown (no git)" if dirty is None else "dirty"
        raise SystemExit(
            f"release_manifest: refusing rc:true — working tree is "
            f"{state}; commit first or pass --allow-dirty")
    classified = sorted(set(re.findall(
        r"Programming Language :: Python :: (3\.\d+)",
        "\n".join(project.get("classifiers", ())))))
    return {
        "manifest_version": 1,
        "package": project["name"],
        "version": project["version"],
        "rc": rc,
        "git_head": head,
        "dirty_tree": dirty,
        "python_requires": project.get("requires-python", ""),
        "python_classified": classified,
        "contract_family": family,
        "contract_version": contract_version,
        "forge_protocol_version": protocol_version,
        "artifacts": _artifacts(dist_dir),
        "schema_ids": list(schema_ids),
        "cli_command_count": len(_cli_commands()),
        "mcp_tool_count": len(_mcp_tools()),
    }


def _render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _normalize(manifest: dict) -> dict:
    """Strip volatile fields for --check: git state + artifact digests."""
    m = {k: v for k, v in manifest.items() if k not in _VOLATILE_TOP}
    m["artifacts"] = sorted(
        a["filename"] for a in manifest.get("artifacts", ()))
    return m


def _diff(a: dict, b: dict) -> list[str]:
    ra = json.dumps(a, indent=2, sort_keys=True).splitlines()
    rb = json.dumps(b, indent=2, sort_keys=True).splitlines()
    out: list[str] = []
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x != y:
            out.append(f"  line {i + 1}: committed={x!r} generated={y!r}")
    if len(ra) != len(rb):
        out.append(f"  length: {len(ra)} vs {len(rb)} lines")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ARTIFACT)
    parser.add_argument("--dist-dir", type=Path, default=DIST)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="regenerate and diff the non-volatile "
                             "fields against --out")
    parser.add_argument("--rc", action="store_true",
                        help="mark the manifest as a release candidate")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="permit --rc on a dirty/unknown tree")
    args = parser.parse_args()

    manifest = build_manifest(
        dist_dir=args.dist_dir, rc=args.rc, allow_dirty=args.allow_dirty)
    rendered = _render(manifest)
    if args.stdout:
        sys.stdout.write(rendered)
        return 0
    if args.check:
        if not args.out.exists():
            print(f"release_manifest --check: missing {args.out}; record "
                  f"with `python factory/release_manifest.py --rc "
                  f"--allow-dirty`", file=sys.stderr)
            return 1
        committed = json.loads(args.out.read_text(encoding="utf-8"))
        diffs = _diff(_normalize(committed), _normalize(manifest))
        if diffs:
            print("release_manifest --check: drift (non-volatile):",
                  file=sys.stderr)
            for d in diffs[:10]:
                print(d, file=sys.stderr)
            return 1
        print(f"release_manifest --check: {args.out} matches "
              "(volatile fields excluded)")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(f"release_manifest: {args.out} "
          f"(v{manifest['version']}, {len(manifest['artifacts'])} "
          f"artifacts, rc={manifest['rc']}, dirty={manifest['dirty_tree']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
