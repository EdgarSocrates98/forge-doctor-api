"""Spec 065 — engine benchmark: cold vs warm incremental scans.

Runs `scan_project` over (a) every realworld lab fixture and (b) a
self-scan of this repository, three ways:

- cold      : `incremental=False` — the default deterministic path;
- populate  : `incremental=True` on an empty cache dir;
- warm      : `incremental=True` against the populated cache.

Per-analyzer wall time + allocations come from `stats_timing=True`
(duration_ms / allocated_bytes — opt-in fields, never canonical).
Equivalence of cold vs warm reports is asserted structurally by the
test suite; this benchmark only measures.

Run:  python factory/benchmarks/engine_benchmark.py
Output: factory/runs/engine-benchmark-<UTC timestamp>.json
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.scan import scan_project

LABS = ROOT / "labs" / "realworld"


def _tool_version() -> str:
    try:
        import tomllib
        data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


def _env() -> dict[str, object]:
    ram: int | None = None
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": ram,
        "tool_version": _tool_version(),
    }


def _per_analyzer(report) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    if report.stats is None:
        return out
    for a in report.stats.analyzers:
        row: dict[str, float | int] = {
            "artifacts": a.artifacts,
            "findings": a.findings,
            "unknowns": a.unknowns,
        }
        if a.duration_ms is not None:
            row["duration_ms"] = round(a.duration_ms, 2)
        if a.allocated_bytes is not None:
            row["allocated_kb"] = round(a.allocated_bytes / 1024, 1)
        out[a.analyzer] = row
    return out


def _run(target: Path, *, incremental: bool) -> dict[str, object]:
    ctx = ProjectContext.from_root(target)
    tracemalloc.start()
    wall0, cpu0 = time.perf_counter(), time.process_time()
    report = scan_project(ctx, incremental=incremental,
                          stats_timing=True)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "wall_s": round(wall, 3),
        "cpu_s": round(cpu, 3),
        "peak_mb": round(peak / 1e6, 2),
        "findings": len(report.findings),
        "unknowns": len(report.unknowns),
        "analyzers": _per_analyzer(report),
    }


def _targets() -> dict[str, Path]:
    targets: dict[str, Path] = {}
    if LABS.is_dir():
        for case in sorted(LABS.iterdir()):
            if case.is_dir():
                targets[f"lab:{case.name}"] = case
    targets["self"] = ROOT
    return targets


def main() -> int:
    results: dict[str, object] = {}
    for name, target in _targets().items():
        cold = _run(target, incremental=False)
        # populate + warm run in place, then remove the cache dir so
        # fixtures and the repo stay clean of .forge-doctor/.
        populate = _run(target, incremental=True)
        warm = _run(target, incremental=True)
        _cleanup(target / ".forge-doctor")
        results[name] = {
            "cold": cold,
            "populate": populate,
            "warm": warm,
            "warm_speedup_x": (
                round(cold["wall_s"] / warm["wall_s"], 2)
                if warm["wall_s"] else None),
            "equivalent": (
                cold["findings"] == warm["findings"]
                and cold["unknowns"] == warm["unknowns"]),
        }
        print(f"{name}: cold={cold['wall_s']}s warm={warm['wall_s']}s "
              f"speedup={results[name]['warm_speedup_x']} "
              f"equivalent={results[name]['equivalent']}")

    record = {
        "benchmark": "engine-cold-warm",
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "env": _env(),
        "results": results,
        "all_equivalent": all(
            r["equivalent"] for r in results.values()),
    }
    runs = ROOT / "factory" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = runs / f"engine-benchmark-{stamp}.json"
    out.write_text(json.dumps(record, indent=2, sort_keys=True),
                   encoding="utf-8")
    print(f"\nrecord: {out}")
    print(f"all_equivalent: {record['all_equivalent']}")
    return 0 if record["all_equivalent"] else 1


def _cleanup(cache_dir: Path) -> None:
    if not cache_dir.is_dir():
        return
    for p in sorted(cache_dir.rglob("*"), reverse=True):
        try:
            p.rmdir() if p.is_dir() else p.unlink()
        except OSError:
            pass
    try:
        cache_dir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
