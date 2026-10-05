"""Spec 030 §181 + spec 076 — streaming/scale benchmark record + gate.

Generates synthetic projects at the spec'd scales and records wall time +
peak Python heap (tracemalloc) for contract parsing and OTLP span
ingestion. Writes `factory/runs/scale-benchmark.json`.

Budget model (spec 076): the committed baseline is the source of truth.
`--check` re-measures the CHECK_SCALES subset and fails when any metric
exceeds `baseline * HEADROOM`:

- `seconds`    — wall time on the measurement host; HEADROOM 4.0x is
                 deliberately coarse (shared CI hardware varies wildly).
                 It exists to catch a pathological blow-up, not a 20%
                 regression — per-scenario perf work uses lab evidence.
- `peak_mb`    — tracemalloc peak heap; HEADROOM 2.5x tolerates
                 allocator noise while catching super-linear leaks.

Refresh policy: `--write-baseline` regenerates the committed record —
only ever in a deliberate regeneration commit, never inside `--check`.

Run:  python factory/benchmarks/scale_benchmark.py [--check|--write-baseline]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.runtime.loader import load_runtime_project
from forge_doctor_api.core.context import ProjectContext

# spec 076 — multiplicative headroom over the committed baseline.
HEADROOM: dict[str, float] = {
    "seconds": 4.0,
    "peak_mb": 2.5,
}
# Scales re-measured by --check (fast enough for CI: ~10s total).
CHECK_SCALES: dict[str, tuple[int, ...]] = {
    "endpoints": (1_000,),
    "spans": (10_000,),
}
# Full measurement scales for --write-baseline / default run.
FULL_SCALES: dict[str, tuple[int, ...]] = {
    "endpoints": (100, 1_000, 10_000),
    "spans": (10_000, 100_000, 1_000_000),
}
BASELINE = ROOT / "factory" / "runs" / "scale-benchmark.json"


def _openapi(count: int) -> str:
    paths = {
        f"/r{i}": {
            "get": {
                "operationId": f"get{i}",
                "responses": {"200": {"description": "ok"}},
            }
        }
        for i in range(count)
    }
    return json.dumps(
        {"openapi": "3.0.3", "info": {"title": "B", "version": "1"},
         "paths": paths})


def _otlp(path: Path, count: int) -> None:
    # write the OTLP document incrementally to bound fixture memory
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"resourceSpans":[{"resource":{"attributes":['
                 '{"key":"service.name","value":{"stringValue":"api"}}]},'
                 '"scopeSpans":[{"scope":{},"spans":[')
        for i in range(count):
            if i:
                fh.write(",")
            fh.write(json.dumps({
                "traceId": f"t{i:08x}", "spanId": f"s{i:08x}",
                "name": "GET /r", "kind": 2,
                "startTimeUnixNano": "0",
                "endTimeUnixNano": str(100 * 10**6),
                "attributes": [
                    {"key": "http.method",
                     "value": {"stringValue": "GET"}},
                    {"key": "http.route",
                     "value": {"stringValue": "/r"}},
                    {"key": "http.status_code",
                     "value": {"intValue": "200"}},
                ],
                "status": {"code": 1},
            }))
        fh.write("]}]}]}")


def _measure(fn):
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, round(elapsed, 3), round(peak / 1e6, 1)


def _run(scales: dict[str, tuple[int, ...]]) -> dict[str, object]:
    record: dict[str, object] = {"tool": "forge-doctor-api",
                                 "results": []}
    results: list[dict[str, object]] = record["results"]  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for count in scales["endpoints"]:
            (root / "openapi.json").write_text(
                _openapi(count), encoding="utf-8")
            ctx = ProjectContext.from_root(root)
            model, secs, mb = _measure(lambda: load_openapi_project(ctx))
            results.append({
                "kind": "endpoints", "scale": count,
                "operations": len(model.operations),
                "seconds": secs, "peak_mb": mb})
            (root / "openapi.json").unlink()
            print(f"endpoints {count}: {secs}s peak {mb}MB")
        for count in scales["spans"]:
            _otlp(root / "traces.json", count)
            ctx = ProjectContext.from_root(root)

            def _run() -> int:
                rt = load_runtime_project(
                    ctx, ["traces.json"], keep_spans=True)
                return len(rt.executions)

            n, secs, mb = _measure(_run)
            results.append({
                "kind": "spans", "scale": count,
                "executions": n,
                "seconds": secs, "peak_mb": mb})
            (root / "traces.json").unlink()
            print(f"spans {count}: {secs}s peak {mb}MB ({n} execs)")
    return record


def _check() -> int:
    """Re-measure CHECK_SCALES and gate against baseline * HEADROOM."""
    if not BASELINE.is_file():
        print(f"baseline missing: {BASELINE} (run --write-baseline)",
              file=sys.stderr)
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ref = {(r["kind"], r["scale"]): r for r in baseline["results"]}
    measured = _run(CHECK_SCALES)["results"]
    failures: list[str] = []
    for entry in measured:  # type: ignore[union-attr]
        key = (entry["kind"], entry["scale"])
        base = ref.get(key)
        if base is None:
            failures.append(f"{key}: no committed baseline entry")
            continue
        for metric, headroom in HEADROOM.items():
            allowed = float(base[metric]) * headroom
            actual = float(entry[metric])
            status = "ok" if actual <= allowed else "OVER BUDGET"
            print(f"  {key} {metric}: {actual} <= "
                  f"{base[metric]}*{headroom} ({status})")
            if actual > allowed:
                failures.append(
                    f"{key} {metric}: {actual} exceeds "
                    f"{base[metric]} * {headroom}")
    if failures:
        print("scale budget failures:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("scale budget: all metrics within headroom")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true",
        help="re-measure CHECK_SCALES and gate vs committed baseline")
    mode.add_argument(
        "--write-baseline", action="store_true",
        help="full-scale run, overwrite factory/runs/scale-benchmark.json")
    args = parser.parse_args()

    if args.check:
        return _check()
    record = _run(FULL_SCALES)
    BASELINE.write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
