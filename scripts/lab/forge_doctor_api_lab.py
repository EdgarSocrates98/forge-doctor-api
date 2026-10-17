#!/usr/bin/env python3
"""Forge Lab emitter — runs the repo's real lab engine (lab.report.run_labs)
over labs/ ground-truth scenario families and emits forge/BenchmarkResult/v1.

Deterministic, offline, stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import re as _re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

FORGE = "forge-doctor-api"
SUITE = "forge-doctor-api-lab"


def _slug(s: object) -> str:
    return _re.sub(r"[^a-z0-9-]+", "-", str(s).lower()).strip("-") or "scenario"


def m(state: str, value: object = None, unit: str = "") -> dict:
    return {"state": state, "unit": unit, "value": value}


def _emit_result(r: dict, elapsed_ms: int) -> dict:
    """One ``forge/BenchmarkResult/v1`` row from a ``run_labs`` result dict.

    ``skipped`` is neither pass nor fail: a minimal install missing an
    optional extra must report ``skipped`` with ``success`` not_available —
    never a fabricated 0.0 failure.
    """
    observed = len(r.get("observed_findings", []))
    missing = len(r.get("missing_findings", []))
    forbidden = len(r.get("forbidden_hits", []))
    expected = observed + missing
    matched = observed
    precision = (matched / observed) if observed else (1.0 if expected == 0 else None)
    recall = (matched / expected) if expected else None
    return {
        "scenario_id": _slug(r.get("name", "unknown")),
        "verdict": "skipped"
        if r.get("skipped")
        else ("pass" if r.get("passed") else "fail"),
        "duration_ms": int(r.get("elapsed_ms", elapsed_ms)),
        "detail": str(r.get("skip_reason", "") or ""),
        "evidence_ref": str(r.get("domain", "")) or "",
        "judge": None,
        "metrics": {
            "success": m("measured", 1.0 if r.get("passed") else 0.0, "ratio")
            if not r.get("skipped")
            else m("not_available"),
            "precision": m("measured", precision, "ratio")
            if precision is not None
            else m("not_available"),
            "recall": m("measured", recall, "ratio")
            if recall is not None
            else m("not_available"),
            "false_positives": m("measured", forbidden),
            "cost_usd": m("not_applicable"),
            "tokens": m("not_applicable"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", required=True)
    ap.add_argument("--mode", default="A", choices=["A", "B", "C"])
    ap.add_argument("--result-out", required=True)
    a = ap.parse_args()
    checkout = Path(a.checkout).resolve()
    sys.path.insert(0, str(checkout / "src"))

    from forge_doctor_api.core.context import ProjectContext
    from forge_doctor_api.lab.report import run_labs

    started = time.monotonic()
    report = run_labs(ProjectContext(checkout))
    data = report.to_dict()
    elapsed = int((time.monotonic() - started) * 1000)

    results = [_emit_result(r, elapsed) for r in data.get("results", [])]

    receipt = {
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "external": False,
        "suite": SUITE,
        "forge": FORGE,
        "mode": a.mode,
        "notes": [f"families={len(data.get('families', []))}"],
        "producer": {"id": FORGE, "version": "lab-script"},
        "results": results,
    }
    out = Path(a.result_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
