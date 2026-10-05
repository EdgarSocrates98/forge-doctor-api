"""Spec 030 §181 + spec 076 + spec 086 — streaming/scale benchmark record + gate.

Generates synthetic projects at the spec'd scales and records wall time +
peak Python heap (tracemalloc) plus the full spec-086 correctness metric
set: executions, completed/incomplete traces, evictions, late spans,
tombstone overflow, and — for the snapshot suite — snapshot file bytes,
load time and diff time. Writes `factory/runs/scale-benchmark.json`.

Correctness is measured, not assumed: every run asserts the assembled
trace inventory equals the generated ground truth and that evictions/
tombstones occur only when the assembly `window` bound is exceeded.

Budget model (spec 076): the committed baseline is the source of truth.
`--check` re-measures the CHECK_SCALES subset and fails when a gated
metric exceeds `baseline * HEADROOM`:

- `wall_seconds` — wall time on the measurement host; HEADROOM 4.0x is
                     deliberately coarse (shared CI hardware varies wildly).
                     It exists to catch a pathological blow-up, not a 20%
                     regression — per-scenario perf work uses lab evidence.
- `peak_bytes`   — tracemalloc peak heap; HEADROOM 2.5x tolerates
                     allocator noise while catching super-linear leaks.

Correctness counters (executions/traces/evictions/tombstones/snapshot
sizes) are recorded for the baseline but gated by assertion inside the
run — a correctness failure aborts the run regardless of headroom.

Refresh policy: `--write-baseline` regenerates the committed record —
only ever in a deliberate regeneration commit, never inside `--check`.

Run:  python factory/benchmarks/scale_benchmark.py [--check|--write-baseline]
"""

from __future__ import annotations

import argparse
import json
import re
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
from forge_doctor_api.scan import scan_project
from forge_doctor_api.temporal import (
    SnapshotStore,
    architectural_regressions,
)

# spec 076 — multiplicative headroom over the committed baseline.
HEADROOM: dict[str, float] = {
    "wall_seconds": 4.0,
    "peak_bytes": 2.5,
}
# Assembly window used for every span run — the documented bound.
WINDOW = 10_000
# Spans per generated trace in the grouped ("steady") span scenario.
SPANS_PER_TRACE = 25
# Late spans appended for still-tombstoned ids in the churn scenario.
LATE_SPANS = 500
# Scales re-measured by --check (fast enough for CI).
CHECK_SCALES: dict[str, tuple[int, ...]] = {
    "endpoints": (5_000,),
    "spans": (50_000,),
    "spans_churn": (50_000,),
}
# Full measurement scales for --write-baseline / default run. The
# recorded envelope is 10k endpoints / 100k spans — no vanity tier.
FULL_SCALES: dict[str, tuple[int, ...]] = {
    "endpoints": (100, 1_000, 5_000, 10_000),
    "spans": (10_000, 50_000, 100_000),
    "spans_churn": (10_000, 50_000, 100_000),
    "snapshots": (10_000,),
}
BASELINE = ROOT / "factory" / "runs" / "scale-benchmark.json"

_EVICTED_RE = re.compile(r"assembly window evicted")
_LATE_RE = re.compile(r"(\d+) span\(s\) for traces already evicted")
_TOMBSTONE_RE = re.compile(r"tombstone capacity for (\d+) evicted")


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


def _span_obj(trace_id: str, span_id: str, parent: str | None) -> str:
    return json.dumps({
        "traceId": trace_id, "spanId": span_id,
        "parentSpanId": parent or "",
        "name": "GET /r", "kind": 2 if parent is None else 3,
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
    })


def _otlp_grouped(path: Path, count: int) -> int:
    """`count` spans grouped into traces of SPANS_PER_TRACE — realistic
    steady input; trace count stays under WINDOW at every scale, so the
    bound is never exceeded and no eviction may occur. Returns the
    generated trace count (ground truth)."""
    traces = count // SPANS_PER_TRACE
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"resourceSpans":[{"resource":{"attributes":['
                 '{"key":"service.name","value":{"stringValue":"api"}}]},'
                 '"scopeSpans":[{"scope":{},"spans":[')
        first = True
        for t in range(traces):
            root = f"s{t:08x}-00"
            for s in range(SPANS_PER_TRACE):
                if not first:
                    fh.write(",")
                first = False
                fh.write(_span_obj(
                    f"t{t:08x}", f"s{t:08x}-{s:02x}",
                    None if s == 0 else root))
        fh.write("]}]}]}")
    return traces


def _otlp_churn(path: Path, count: int) -> tuple[int, int]:
    """`count` spans with a unique trace_id each — worst-case churn that
    exceeds the WINDOW bound at scale > WINDOW, forcing measured
    evictions/tombstones. LATE_SPANS extra spans are appended for the
    most recently evicted ids (still tombstoned) to measure late-span
    accounting. Returns (generated trace count, late span count)."""
    evictions = max(0, count - WINDOW)
    late_ids = max(0, evictions - LATE_SPANS)  # first late-target index
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"resourceSpans":[{"resource":{"attributes":['
                 '{"key":"service.name","value":{"stringValue":"api"}}]},'
                 '"scopeSpans":[{"scope":{},"spans":[')
        for i in range(count):
            if i:
                fh.write(",")
            fh.write(_span_obj(f"t{i:08x}", f"s{i:08x}", None))
        late = 0
        if evictions:
            for i in range(late_ids, evictions):
                fh.write(",")
                fh.write(_span_obj(
                    f"t{i:08x}", f"s{i:08x}-late", None))
                late += 1
        fh.write("]}]}]}")
    return count, late


def _measure(fn):
    tracemalloc.start()
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, round(elapsed, 3), peak


def _rt_metrics(rt) -> dict[str, int]:
    """Correctness counters from the bounded runtime summary — all
    derived from emitted models/unknowns, never from internals."""
    evictions = 0
    for t in rt.traces:
        if any(_EVICTED_RE.search(u.missing) for u in t.unknowns):
            evictions += 1
    late_spans = 0
    tombstone_overflow = 0
    for u in rt.unknowns:
        if m := _LATE_RE.search(u.missing):
            late_spans += int(m.group(1))
        if m := _TOMBSTONE_RE.search(u.missing):
            tombstone_overflow += int(m.group(1))
    completed = sum(1 for t in rt.traces if not t.incomplete)
    return {
        "executions": len(rt.executions),
        "traces_completed": completed,
        "traces_incomplete": len(rt.traces) - completed,
        "evictions": evictions,
        "late_spans": late_spans,
        "tombstone_overflow": tombstone_overflow,
    }


def _run(scales: dict[str, tuple[int, ...]]) -> dict[str, object]:
    record: dict[str, object] = {"tool": "forge-doctor-api",
                                 "window": WINDOW,
                                 "results": []}
    results: list[dict[str, object]] = record["results"]  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for count in scales["endpoints"]:
            (root / "openapi.json").write_text(
                _openapi(count), encoding="utf-8")
            ctx = ProjectContext.from_root(root)
            model, secs, peak = _measure(lambda: load_openapi_project(ctx))
            assert len(model.operations) == count, (
                f"endpoints {count}: parsed {len(model.operations)}")
            results.append({
                "kind": "endpoints", "scale": count,
                "operations": len(model.operations),
                "wall_seconds": secs, "peak_bytes": peak})
            (root / "openapi.json").unlink()
            print(f"endpoints {count}: {secs}s peak {peak / 1e6:.1f}MB")
        for count in scales.get("spans", ()):
            traces = _otlp_grouped(root / "traces.json", count)
            ctx = ProjectContext.from_root(root)

            def _grouped() -> dict[str, int]:
                rt = load_runtime_project(
                    ctx, ["traces.json"], keep_spans=True,
                    window=WINDOW)
                m = _rt_metrics(rt)
                # Ground truth: every trace under the window — complete,
                # unevicted, one execution per server root.
                assert len(rt.traces) == traces, (
                    f"traces {len(rt.traces)} != generated {traces}")
                assert m["traces_completed"] == traces
                assert m["traces_incomplete"] == 0
                assert m["evictions"] == 0 and m["late_spans"] == 0
                assert m["executions"] == traces
                assert all(
                    t.span_count == SPANS_PER_TRACE for t in rt.traces)
                return m

            m, secs, peak = _measure(_grouped)
            results.append({
                "kind": "spans", "scale": count,
                "wall_seconds": secs, "peak_bytes": peak, **m})
            (root / "traces.json").unlink()
            print(f"spans {count}: {secs}s peak {peak / 1e6:.1f}MB "
                  f"({m['executions']} execs, {m['traces_completed']} "
                  "traces complete)")
        for count in scales.get("spans_churn", ()):
            traces, late = _otlp_churn(root / "traces.json", count)
            ctx = ProjectContext.from_root(root)

            def _churn() -> dict[str, int]:
                rt = load_runtime_project(
                    ctx, ["traces.json"], keep_spans=True,
                    window=WINDOW)
                m = _rt_metrics(rt)
                # Ground truth: `count` distinct tids. Evictions happen
                # iff count > WINDOW; late spans hit tombstones without
                # reassembling; tombstone overflow only beyond the
                # tombstone limit (= WINDOW default).
                expected_evictions = max(0, count - WINDOW)
                assert len(rt.traces) == traces, (
                    f"traces {len(rt.traces)} != generated {traces}")
                assert m["evictions"] == expected_evictions, (
                    f"evictions {m['evictions']} != "
                    f"{expected_evictions}")
                assert m["traces_incomplete"] == expected_evictions
                assert m["traces_completed"] == count - expected_evictions
                assert m["late_spans"] == late, (
                    f"late {m['late_spans']} != {late}")
                assert m["tombstone_overflow"] == max(
                    0, expected_evictions - WINDOW)
                assert m["executions"] == count
                return m

            m, secs, peak = _measure(_churn)
            results.append({
                "kind": "spans_churn", "scale": count,
                "wall_seconds": secs, "peak_bytes": peak, **m})
            (root / "traces.json").unlink()
            print(f"spans_churn {count}: {secs}s peak "
                  f"{peak / 1e6:.1f}MB ({m['evictions']} evictions, "
                  f"{m['late_spans']} late, "
                  f"{m['tombstone_overflow']} tombstone overflow)")
        for count in scales.get("snapshots", ()):
            (root / "openapi.json").write_text(
                _openapi(count), encoding="utf-8")
            traces = _otlp_grouped(root / "traces.json", 10_000)
            ctx = ProjectContext.from_root(root)
            report, secs, peak = _measure(
                lambda: scan_project(ctx, keep_spans=True))
            assert report.runtime is not None
            store_dir = root / "snaps"
            store = SnapshotStore(store_dir)

            _, save_secs, _ = _measure(
                lambda: store.save(
                    report, label=f"scale-{count}",
                    created_at=None))
            snap = store.list()[0]
            snap_bytes = (store_dir / f"{snap.id}.json").stat().st_size
            loaded, load_secs, _ = _measure(
                lambda: store.report(snap.id))
            regs, diff_secs, _ = _measure(
                lambda: architectural_regressions(loaded, report))
            # Round-trip preservation of the bounded runtime summary.
            assert loaded.runtime is not None
            assert loaded.runtime == report.runtime
            assert regs == (), f"self-diff found {len(regs)} regressions"
            results.append({
                "kind": "snapshot", "scale": count,
                "wall_seconds": secs, "peak_bytes": peak,
                "snapshot_bytes": snap_bytes,
                "snapshot_load_seconds": load_secs,
                "snapshot_diff_seconds": diff_secs,
                "snapshot_save_seconds": save_secs})
            (root / "openapi.json").unlink()
            (root / "traces.json").unlink()
            print(f"snapshot {count}: {snap_bytes}B "
                  f"load {load_secs}s diff {diff_secs}s "
                  f"(scan {secs}s peak {peak / 1e6:.1f}MB, "
                  f"{traces} traces)")
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
