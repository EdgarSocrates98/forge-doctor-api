You are implementing Loop Factory spec `042-runtime-aggregation`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\042-runtime-aggregation.md`
        Spec hash: `0520c35485765597d81649505eadeb859bf8f3e7e7e0ec4f1a041e1fe21e2278`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
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
