---
id: 042-runtime-aggregation
title: Runtime online aggregation — incremental stats without dataset retention
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §19, §20.
- Problem: perf/observability signals need exact percentile/aggregate
  data; computing them today requires materializing all executions —
  defeats bounded memory (spec 041).
- Out of scope: changing finding thresholds/rules; approximate
  quantiles where exact is cheap enough (per-group bounded samples —
  groups are the small dimension, spans are the big one).
- Review failure: silently approximate numbers presented as exact;
  aggregators that keep per-request objects; signal values that change
  vs the batch path on the same input.
- Riskiest assumption: percentile precision — RESOLVED: exact
  percentile within bounded per-group reservoirs is fine because
  groups (service+operation+window) are small; reservoir cap with
  documented semantics (deterministic reservoir sampling, labelled
  `approximate=True` when it kicked in).
- Smallest acceptable: `RequestAggregator` + per-signal aggregators
  consuming the execution stream, emitting the same
  `RequestExecution`-derived models used by perf checks + tests.

# Context

§19: online aggregators — TraceAssembler, RequestAggregator,
LatencyAggregator, ErrorAggregator, FanoutAggregator, RetryAggregator,
PayloadAggregator, DownstreamAggregator, SloAggregator. §20:
incremental statistics, quantile approximations only when justified
and marked.

# Acceptance Criteria

- `analyzers/runtime/aggregate.py`: aggregators consuming
  `RequestExecution`/span iterators emitting:
  latency percentiles per (service, operation), error rates, fanout
  counts, retry patterns, payload sizes, downstream call counts,
  SLO-window counters — as frozen summary models.
- Exact where bounded; where a cap can be hit, output carries an
  explicit `approximate` flag + the cap used — never silent rounding.
- `executions_from_traces` path refactored so perf checks can run on
  streamed executions (iterator in, same findings out on fixtures).
- Unit tests: parity batch-vs-stream on lab runtime fixtures, cap-hit
  labelling, determinism, empty input.
- pytest/ruff/mypy pass.

# Constraints

- Aggregation output models carry evidence of their mode (exact vs
  approximate); UNKNOWN semantics unchanged.
