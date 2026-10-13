"""Spec 043 — runtime streaming benchmark + regression gate.

Deterministic input: a seeded generator emits interleaved OTLP spans
(no clock data) through `load_runtime_project`'s bounded streaming
path. Per-size metrics + an environment record land in
`factory/runs/runtime-benchmark-<UTC timestamp>.json`.

Run:      python factory/benchmarks/runtime_benchmark.py
Compare:  python factory/benchmarks/runtime_benchmark.py --compare
          (deltas vs latest prior record; `regression: true` when
          spans/sec or peak-mb-per-1k-spans degrades > 25%)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from forge_doctor_api.analyzers.runtime.loader import load_runtime_project
from forge_doctor_api.core.context import ProjectContext

SIZES = (10_000, 100_000, 500_000)
SEED = 0xF0A6E
REGRESSION_THRESHOLD = 0.25


def _write_otlp(path: Path, spans: int, *, seed: int, traces: int) -> None:
    """Seeded interleaved span stream — worst case for the window."""
    rng = random.Random(seed)
    span_ids: dict[int, int] = {}
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"resourceSpans":[{"resource":{"attributes":['
                 '{"key":"service.name","value":{"stringValue":"bench"}}]},'
                 '"scopeSpans":[{"scope":{},"spans":[')
        for i in range(spans):
            if i:
                fh.write(",")
            t = rng.randrange(traces)
            s = span_ids.get(t, 0)
            span_ids[t] = s + 1
            parent = f'"parentSpanId":"s{t:08x}-{s - 1:04x}",' if s else ""
            fh.write(
                '{"traceId":"t%08x","spanId":"s%08x-%04x",%s'
                '"name":"GET /r%d","kind":2,'
                '"startTimeUnixNano":"%d","endTimeUnixNano":"%d",'
                '"status":{"code":1}}'
                % (t, t, s, parent, t % 7, i * 1000, i * 1000 + 10**7))
        fh.write("]}]}]}")


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


def _tool_version() -> str:
    try:
        import tomllib
        data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


def _measure(root: Path, spans: int) -> dict[str, object]:
    target = root / "traces.json"
    mb_in = round(target.stat().st_size / 1e6, 2)
    ctx = ProjectContext.from_root(root)
    tracemalloc.start()
    wall0, cpu0 = time.perf_counter(), time.process_time()
    rt = load_runtime_project(ctx, ["traces.json"], keep_spans=False)
    wall = time.perf_counter() - wall0
    cpu = time.process_time() - cpu0
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    complete = sum(1 for t in rt.traces if not t.incomplete)
    return {
        "spans": spans,
        "mb_in": mb_in,
        "wall_s": round(wall, 3),
        "cpu_s": round(cpu, 3),
        "peak_mb": round(peak / 1e6, 2),
        "peak_mb_per_1k_spans": round(peak / 1e6 / (spans / 1000), 3),
        "spans_per_s": round(spans / wall) if wall else None,
        "mb_per_s": round(mb_in / wall, 2) if wall else None,
        "traces": len(rt.traces),
        "trace_completion_rate": round(complete / len(rt.traces), 4)
        if rt.traces else None,
        "executions": len(rt.executions),
        "unknown_rate": round(len(rt.unknowns) / spans, 6),
    }


def _latest_record(exclude: Path) -> Path | None:
    runs = sorted(
        (ROOT / "factory" / "runs").glob("runtime-benchmark-*.json"))
    for p in reversed(runs):
        if p != exclude:
            return p
    return None


def _compare(current: dict[str, object], previous: dict[str, object]
             ) -> dict[str, object]:
    prev_by_size = {
        int(r["spans"]): r
        for r in previous.get("results", [])  # type: ignore[union-attr]
    }
    deltas: list[dict[str, object]] = []
    regression = False
    for row in current["results"]:  # type: ignore[union-attr]
        prev = prev_by_size.get(int(row["spans"]))
        if prev is None:
            continue
        delta: dict[str, object] = {"spans": row["spans"]}
        for metric in ("spans_per_s", "peak_mb_per_1k_spans",
                       "wall_s", "mb_per_s"):
            cur_v, prev_v = row.get(metric), prev.get(metric)
            if isinstance(cur_v, (int, float)) and isinstance(
                prev_v, (int, float)) and prev_v:
                change = (cur_v - prev_v) / prev_v
                delta[metric] = round(change, 4)
                worse = (
                    change < -REGRESSION_THRESHOLD
                    if metric in ("spans_per_s", "mb_per_s")
                    else change > REGRESSION_THRESHOLD
                )
                regression = regression or worse
        deltas.append(delta)
    return {"deltas": deltas, "regression": regression}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true",
                    help="diff against the latest prior record")
    ap.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    args = ap.parse_args()

    record: dict[str, object] = {
        "tool": "forge-doctor-api",
        "kind": "runtime-streaming",
        "env": _env(),
        "results": [],
    }
    results: list[dict[str, object]] = record["results"]  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for n in args.sizes:
            traces = max(64, n // 10)
            _write_otlp(root / "traces.json", n, seed=SEED, traces=traces)
            row = _measure(root, n)
            results.append(row)
            print(f"spans {n}: {row['wall_s']}s peak {row['peak_mb']}MB "
                  f"({row['spans_per_s']}/s, "
                  f"completion {row['trace_completion_rate']})")
            (root / "traces.json").unlink()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "factory" / "runs" / f"runtime-benchmark-{stamp}.json"
    if args.compare:
        prev_path = _latest_record(out)
        if prev_path is not None:
            prev = json.loads(prev_path.read_text("utf-8"))
            record["comparison"] = _compare(record, prev)
            record["compared_to"] = prev_path.name
            if record["comparison"]["regression"]:  # type: ignore[index]
                print("REGRESSION detected vs", prev_path.name)
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
