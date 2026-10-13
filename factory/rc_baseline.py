"""Spec 081 — RC baseline artifact generator.

Emits `docs/rc-baseline.json`: the measured facts this RC wave is
evaluated against — versions, public-surface counts, corpus/lab/scale
numbers, dependency inventory. Deterministic (sorted, no wall-clock);
`--check` regenerates and diffs against the committed artifact —
drift means a public surface moved without re-freezing the baseline.

Run:  python factory/rc_baseline.py [--check|--stdout|--out PATH]
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
ARTIFACT = ROOT / "docs" / "rc-baseline.json"


def _pyproject() -> dict:
    return tomllib.loads(
        (ROOT / "pyproject.toml").read_text("utf-8"))["project"]


def _src_on_path() -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))


def _cli_commands() -> tuple[str, ...]:
    _src_on_path()
    from forge_doctor_api.cli.catalog import command_inventory
    return tuple(e.path for e in command_inventory())


def _mcp_tools() -> tuple[str, ...]:
    """MCP tool names — regex over the server source so the generator
    never needs the optional `mcp` extra installed."""
    src = (SRC / "forge_doctor_api" / "handoff" /
           "mcp_server.py").read_text(encoding="utf-8")
    return tuple(sorted(set(re.findall(r'"(doctor\.[a-z_]+)"', src))))


def _contract_facts() -> tuple[str, tuple[str, ...], int]:
    _src_on_path()
    from forge_doctor_api.contracts.schemas import FORGE_CONTRACT_SCHEMAS
    from forge_doctor_api.contracts.version import CURRENT
    from forge_doctor_api.handoff.protocol import PROTOCOL_VERSION
    return (str(CURRENT), tuple(sorted(FORGE_CONTRACT_SCHEMAS)),
            PROTOCOL_VERSION)


def _count(pattern: str, path: Path) -> int:
    return len(re.findall(pattern, path.read_text(encoding="utf-8"),
                          re.MULTILINE))


def _scale_facts() -> tuple[dict, dict]:
    src = (ROOT / "factory" / "benchmarks" /
           "scale_benchmark.py").read_text(encoding="utf-8")
    check = re.search(
        r"CHECK_SCALES:\s*dict[^=]*=\s*\{(?P<body>[^}]*)\}",
        src, re.DOTALL)
    headroom = re.search(
        r"HEADROOM:\s*dict[^=]*=\s*\{(?P<body>[^}]*)\}",
        src, re.DOTALL)
    scales: dict[str, list[int]] = {}
    for kind, nums in re.findall(
            r'"(\w+)":\s*\(([\d_,\s]*)\)', check.group("body")):
        scales[kind] = sorted(
            int(n.replace("_", "")) for n in nums.split(",") if n.strip())
    room = {
        k: float(v) for k, v in re.findall(
            r'"(\w+)":\s*([\d.]+)', headroom.group("body"))
    }
    return scales, room


def _sbom_component_count() -> int:
    artifact = ROOT / "factory" / "artifacts" / "sbom.cdx.json"
    if artifact.is_file():
        return len(json.loads(
            artifact.read_text(encoding="utf-8"))["components"])
    return 0


def build_baseline() -> dict:
    project = _pyproject()
    contract_version, schema_ids, protocol_version = _contract_facts()
    check_scales, headroom = _scale_facts()
    deps = sorted(
        re.match(r"([A-Za-z0-9_.-]+)", d).group(1)  # type: ignore[union-attr]
        for d in project.get("dependencies", ()))
    extras = sorted(project.get("optional-dependencies", {}))
    classified = sorted(set(re.findall(
        r"Programming Language :: Python :: (3\.\d+)",
        "\n".join(project.get("classifiers", ())))))
    cli = _cli_commands()
    mcp = _mcp_tools()
    oss_manifest = ROOT / "tests" / "fixtures" / "oss" / "manifest.yaml"
    neg_manifest = (ROOT / "tests" / "fixtures" / "oss-negative" /
                    "manifest.yaml")
    return {
        "baseline_version": 1,
        "version": project["version"],
        "python_requires": project.get("requires-python", ""),
        "python_classified": classified,
        "cli_command_count": len(cli),
        "cli_commands": list(cli),
        "mcp_tool_count": len(mcp),
        "mcp_tools": list(mcp),
        "contract_version": contract_version,
        "contract_schema_ids": list(schema_ids),
        "forge_protocol_version": protocol_version,
        "lab_scenario_count": len(
            list((ROOT / "labs").rglob("expected.yaml"))),
        "oss_slice_count": _count(r"^- name:", oss_manifest),
        "oss_negative_count": _count(r"^- name:", neg_manifest),
        "test_file_count": len(
            list((ROOT / "tests").glob("test_*.py"))),
        "scale_check_scales": check_scales,
        "scale_headroom": headroom,
        "sbom_dependency_count": _sbom_component_count(),
        "runtime_dependencies": deps,
        "optional_extras": extras,
    }


def _render(baseline: dict) -> str:
    return json.dumps(baseline, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ARTIFACT)
    parser.add_argument("--stdout", action="store_true",
                        help="print the baseline instead of writing")
    parser.add_argument("--check", action="store_true",
                        help="regenerate and diff against --out; "
                             "exits non-zero on drift")
    args = parser.parse_args()
    rendered = _render(build_baseline())
    if args.stdout:
        sys.stdout.write(rendered)
        return 0
    if args.check:
        if not args.out.exists():
            print(f"rc_baseline --check: missing {args.out}; record "
                  f"with `python factory/rc_baseline.py`",
                  file=sys.stderr)
            return 1
        committed = args.out.read_text(encoding="utf-8")
        if committed != rendered:
            for i, (have, want) in enumerate(zip(
                    committed.splitlines(), rendered.splitlines())):
                if have != want:
                    print(f"first diff at line {i + 1}:",
                          file=sys.stderr)
                    print(f"  committed: {have}", file=sys.stderr)
                    print(f"  generated: {want}", file=sys.stderr)
                    break
            print(f"rc_baseline --check: drift — regenerate with "
                  f"`python factory/rc_baseline.py`", file=sys.stderr)
            return 1
        print(f"rc_baseline --check: {args.out} matches reality")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    data = json.loads(rendered)
    print(f"rc_baseline: {args.out} "
          f"({data['cli_command_count']} commands, "
          f"{data['mcp_tool_count']} MCP tools, "
          f"{data['oss_slice_count']}+{data['oss_negative_count']} "
          f"corpus slices, {data['test_file_count']} test files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
