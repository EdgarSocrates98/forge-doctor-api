"""Spec 089 — dogfood gate: self-scan baseline shape diff.

Runs the real CLI `scan . --format report` against this repository and
diffs the result against `factory/runs/doctor-self-scan-v0.1.json`.

The gate compares the *shape* of the report — finding identity
(`id`, `severity`, `confidence`, `entity_ids`), unknown identity
(`subject`, `missing`), gate result, schema/tool/knowledge versions.
Whitelisted volatile fields (`description`, `evidence`,
`source_location`, `remediation`, `stats`) move whenever repository
files move lines; they are per-finding annotations, not identity.

Drift means analyzer behavior changed on this repository — re-record
the baseline (`--record`) and review the diff before accepting.

Run:  python factory/self_scan.py [--check|--record|--stdout]
      [--baseline factory/runs/doctor-self-scan-v0.1.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "factory" / "runs" / "doctor-self-scan-v0.1.json"


def _run_scan() -> dict:
    env = dict(os.environ)
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-m", "forge_doctor_api", "scan", ".",
         "--format", "report"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if out.returncode not in (0, 1):  # 1 = gate findings present
        raise SystemExit(
            f"self_scan: scan exited {out.returncode}\n"
            f"{out.stderr[-2000:]}")
    return json.loads(out.stdout)


def _shape(report: dict) -> dict:
    return {
        "schema_version": report.get("schema_version"),
        "tool_version": report.get("tool_version"),
        "knowledge_versions": report.get("knowledge_versions"),
        "gate_passed": report.get("gate_passed"),
        "gate_failures": sorted(report.get("gate_failures") or ()),
        "findings": sorted(collections.Counter(
            (f.get("id"), f.get("severity"), f.get("confidence"),
             tuple(sorted(f.get("entity_ids") or ())))
            for f in report.get("findings", ())
        ).items()),
        "unknowns": sorted(collections.Counter(
            (u.get("subject"), u.get("missing"))
            for u in report.get("unknowns", ())
        ).items()),
    }


def _diff_shape(old: dict, new: dict) -> list[str]:
    out: list[str] = []
    for key in ("schema_version", "tool_version", "knowledge_versions",
                "gate_passed", "gate_failures"):
        if old.get(key) != new.get(key):
            out.append(f"{key}: {old.get(key)!r} != {new.get(key)!r}")
    for field in ("findings", "unknowns"):
        a = dict(old.get(field) or ())
        b = dict(new.get(field) or ())
        for k in set(a) | set(b):
            if a.get(k, 0) != b.get(k, 0):
                out.append(
                    f"{field} {k}: baseline={a.get(k, 0)} "
                    f"current={b.get(k, 0)}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record", action="store_true",
                        help="rewrite the baseline report file")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = _run_scan()
    if args.stdout:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0
    if args.record:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"self_scan: recorded {args.baseline} "
              f"({len(report.get('findings', ()))} findings, "
              f"{len(report.get('unknowns', ()))} unknowns)")
        return 0
    if args.check:
        if not args.baseline.is_file():
            print(f"self_scan --check: missing {args.baseline}; "
                  "record with `python factory/self_scan.py --record`",
                  file=sys.stderr)
            return 1
        old = json.loads(args.baseline.read_text(encoding="utf-8"))
        diffs = _diff_shape(_shape(old), _shape(report))
        if diffs:
            print("self_scan --check: self-scan shape drifted:",
                  file=sys.stderr)
            for d in diffs[:20]:
                print(f"  {d}", file=sys.stderr)
            print("re-record with `python factory/self_scan.py "
                  "--record` after review", file=sys.stderr)
            return 1
        print(f"self_scan --check: shape matches {args.baseline.name} "
              f"({len(report.get('findings', ()))} findings)")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
