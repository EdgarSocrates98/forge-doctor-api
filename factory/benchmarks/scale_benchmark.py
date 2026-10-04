"""Spec 030 §181 — streaming/scale benchmark record.

Generates synthetic projects at the spec'd scales and records wall time +
peak Python heap (tracemalloc) for contract parsing and OTLP span
ingestion. Writes `factory/runs/scale-benchmark.json`.

Run:  python factory/benchmarks/scale_benchmark.py
"""

from __future__ import annotations

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


def main() -> None:
    record: dict[str, object] = {"tool": "forge-doctor-api",
                                 "results": []}
    results: list[dict[str, object]] = record["results"]  # type: ignore[assignment]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for count in (100, 1_000, 10_000):
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
        for count in (10_000, 100_000, 1_000_000):
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
    out = ROOT / "factory" / "runs" / "scale-benchmark.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {out}")


if __name__ == "__main__":
    main()
