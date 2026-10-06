# ADR-0002 — `keep_spans=False` default and bounded runtime retention

- Status: accepted
- Date: 2026

## Context

Runtime evidence (OTLP traces) arrives unbounded: real exports carry
hundreds of thousands of spans. The original loader materialized every
span object plus per-trace lists in memory — linear growth, and every
derived structure (`all_spans`, `all_summaries`) duplicated it again.
Memory blowups made the runtime domain unusable on real exports.

## Decision

The streaming assembler (`runtime/stream.py`) keeps only what the
analysis needs:

- `keep_spans=False` is the default everywhere — spans are aggregated
  into summaries/executions during assembly, then dropped.
- Trace completion tracking is windowed: incomplete-trace state is
  evicted by a bounded window rather than held forever.
- Per-trace executions are derived during assembly
  (`executions_from_traces` was refactored so trace-level derivation
  never requires retained span bodies).
- Raw spans are never stored, exported, or snapshotted — only compact
  summaries, executions and unknowns enter models.

## Consequences

- Memory is bounded by the window size, not the export size;
  `runtime_benchmark.py` proves sublinear growth at 500k spans.
- Interleaved streams beyond the window honestly report
  `incomplete=True` instead of pretending completeness.
- `keep_spans=True` remains an explicit opt-in for debugging — never
  the default, never required by checks.

## Alternatives

- **Two-pass analysis over files** — rejected: doubles I/O and
  complicates every analyzer for a memory shape achievable
  single-pass.
- **Spill to disk** — rejected: introduces persistence concerns
  (secrets, determinism of spill order) far above its value.
- **Cap-and-truncate streams** — rejected: silently dropping tails
  hides evidence; eviction must be declared via `incomplete` flags.
