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

`factory/benchmarks/scale_benchmark.py` records the full spec-086
metric set into `factory/runs/scale-benchmark.json` (committed
baseline): per scale — `wall_seconds`, `peak_bytes`, plus executions,
completed/incomplete traces, evictions, late spans and tombstone
overflow for the span scenarios; snapshot file bytes, load time and
diff time for the snapshot suite.

```bash
python factory/benchmarks/scale_benchmark.py --check          # gate
python factory/benchmarks/scale_benchmark.py --write-baseline # refresh
```

`--check` re-measures the check tier (`CHECK_SCALES`: 5k endpoints,
50k grouped spans, 50k churn spans) and fails when a gated metric
exceeds `baseline * HEADROOM`. Headroom is per-metric in the file
header: `wall_seconds` 4.0x (shared-CI timing variance), `peak_bytes`
2.5x. The gate catches pathological blow-ups, not minor regressions —
per-scenario precision lives in the lab suite.

**Baseline refresh policy:** the committed baseline is regenerated
only via `--write-baseline` in a deliberate commit — never inside
`--check`, never opportunistically when hardware drifts.

## Measured envelope

Two tiers, both measured — nothing in the baseline is asserted
without a recorded run:

| Tier | Contents | Where |
| --- | --- | --- |
| check | 5,000 endpoints · 50,000 grouped spans · 50,000 churn spans | CI `--check` gate |
| recorded | + 100/1k/10k endpoints · 10k/50k/100k spans both shapes · 10k-endpoint snapshot write/load/diff | `--write-baseline` record |

Span scenarios measure both sides of the assembly bound:

- **`spans`** — grouped input (25 spans/trace) keeps the trace count
  under `window`; assertions require zero evictions and every
  generated trace completed.
- **`spans_churn`** — one trace_id per span exceeds `window` past
  10k; assertions require exactly `count - window` evictions,
  `late_spans` hitting still-tombstoned ids, and tombstone overflow
  equal to `evictions - tombstone_limit`. Nothing is assumed: each
  run aborts if the assembled inventory differs from the generated
  ground truth.

The snapshot suite writes a full `scan_project` report (10k
endpoints + 10k spans), records the file bytes, reloads it, and runs
`architectural_regressions` against the live report — a self-diff
must be empty and the bounded runtime summary must round-trip
unchanged. It runs at the recorded tier only, so CI stays fast;
`docs/release-evidence.md` carries the committed numbers.

Edge cases past the bound are pinned by
`tests/test_runtime_stream.py`: late spans after close, duplicate
span ids (incl. the self-parent cycle that once hung
`_critical_path`), out-of-order arrival, missing parents, eviction
under the bound, and tombstone-limit accounting — each with
observable expected output.

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
