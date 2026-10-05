# Runtime, temporal & scale proof

The engine's scaling claims are enforced, not asserted: a committed
baseline, a CI gate, and tests that prove bounds hold regardless of
corpus size.

## Streaming bounds

`analyzers/runtime/stream.py` (`TraceAssembler`) keeps at most
`window` open trace buckets (LRU). What happens beyond the bound is
recorded, never silent:

- **eviction** — an evicted trace still emits its `TraceModel` with
  `incomplete=True` plus an `UnknownFact`
- **tombstones** — evicted trace ids are remembered (bounded by
  `tombstone_limit`, default = `window`); late spans are counted as
  `late_spans`, never reassembled into a new partial trace
- **retention** — `max_spans_per_trace` caps retained span rows per
  trace; truncation is recorded as an `UnknownFact`

Memory is bounded by `window` open buckets plus compact result models
— never by the raw dataset. `tests/test_scale_proof.py` proves the
caps hold at 10x corpus size.

## Memory curve

`test_endpoint_memory_growth_sub_quadratic` measures `tracemalloc`
peak heap at 1k/4k/8k synthesized endpoints and asserts the
*per-endpoint* cost stays within 4x of the small-corpus rate. That
bound is generous enough to ignore allocator noise and fatal to any
super-linear regression (a quadratic curve shows ~linear growth in
per-op cost).

RSS measurement uses stdlib `tracemalloc` only — no `psutil`/
`resource` dependency, so the test runs identically on Windows CI.

## Perf budget gate

`factory/benchmarks/scale_benchmark.py` records wall time + peak heap
for contract parsing and OTLP ingestion into
`factory/runs/scale-benchmark.json` (committed baseline).

```bash
python factory/benchmarks/scale_benchmark.py --check          # gate
python factory/benchmarks/scale_benchmark.py --write-baseline # refresh
```

`--check` re-measures a fast subset (`CHECK_SCALES`: 1k endpoints,
10k spans — ~10s on CI) and fails when any metric exceeds
`baseline * HEADROOM`. Headroom is per-metric in the file header:
`seconds` 4.0x (shared-CI timing variance), `peak_mb` 2.5x. The gate
catches pathological blow-ups, not minor regressions — per-scenario
precision lives in the lab suite.

**Baseline refresh policy:** the committed baseline is regenerated
only via `--write-baseline` in a deliberate commit — never inside
`--check`, never opportunistically when hardware drifts.

## Temporal snapshots

`SnapshotStore` files carry a `snapshot_format` envelope version:

- missing key → legacy format 1, loads unchanged (additive report
  fields decode via model defaults — forward-compat by design)
- `snapshot_format > SNAPSHOT_FORMAT` → `SnapshotError` naming the
  newer format — a versioned reject with reason, never a silent
  misread

Tombstone semantics round-trip through the store: an operation
removed between snapshots is absent from the current report but
visible to `compute_delta` (`operations_removed`) and to
`architectural_regressions` (`APITEMP003`) after reload — removal is
history, not amnesia.

## Invariants

- No wall-clock reads in engine code (`created_at`, `today` are
  injected); the benchmark harness times, but thresholds never assert
  wall-clock correctness on shared CI.
- Nothing unbounded: every stream/retention cap records an unknown
  when it bites.
