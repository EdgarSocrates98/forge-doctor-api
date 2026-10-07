You are implementing Loop Factory spec `041-runtime-streaming`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\041-runtime-streaming.md`
        Spec hash: `9f231002d6bf94d85615c83c477fd7ea51ec3c72a438c70a0ce73b31811383d0`

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

- Owner: project owner; decisions sourced from prompt §17-§21, §18
  ("validate with profiling, do not assume").
- Problem: `load_runtime_project` streams reads but accumulates
  `all_spans`/`all_summaries` — memory is O(dataset): ~1.7 GB @ 1M
  spans (recorded benchmark). Streaming input ≠ streaming processing.
- Out of scope: changing OTLP/accesslog decoders; distributed storage;
  changing TraceModel semantics for callers that legitimately need
  spans (they get bounded retention).
- Review failure: a "streaming" rewrite that still sorts the whole
  span list per file; trace trees silently dropped without unknowns;
  different model output on the same input vs old path (semantic
  regression).
- Riskiest assumption: trace assembly needs the full span set —
  RESOLVED: group spans into per-trace buckets keyed by trace_id via a
  bounded map; spans for the same trace are adjacent in typical OTLP
  exports but NOT guaranteed → bounded window + explicit `incomplete`
  + unknowns for evicted/late spans (§20 trace-completion heuristics
  with explicit unknowns).
- Smallest acceptable: `TraceAssembler` streaming traces out per
  artifact in deterministic order + summaries streamed + memory
  bounded by window, not dataset + unknowns for evicted traces + same
  model outputs on lab fixtures.

# Context

§19 target: artifact → decoder → bounded trace assembler →
RequestExecution → online aggregators → summary → discard raw objects.
§20: bounded windows, stream grouping, incremental stats, spill-free;
approximations labelled. §21: keep_spans default false, bounded
retention when needed.

# Acceptance Criteria

- `analyzers/runtime/stream.py`: `TraceAssembler` — accepts spans in
  artifact order, emits `TraceModel`s in deterministic order (sorted
  by trace_id); bounded `window` (default e.g. 10_000 traces); when a
  trace is evicted incomplete it emits `incomplete=True` + UnknownFact
  (never silently dropped); flush at end emits remaining traces.
- `load_runtime_project` rewritten to drive the assembler per
  artifact: spans and summaries consumed as iterators; no
  `all_spans`/`all_summaries` lists. `keep_spans` still available but
  bounded (`max_spans_per_trace` guard, default off).
- Same TraceModel/observability outputs on existing fixtures; unknowns
  added only where retention was previously guaranteed.
- Memory bound proven by test: synthetic generator of N spans → peak
  traced via tracemalloc stays under a dataset-independent threshold
  (assert scaling factor, not absolute bytes).
- Determinism: output order independent of input chunk boundaries.
- pytest/ruff/mypy pass.

# Constraints

- No spill-to-disk in this spec (roadmap); no new deps.
- Approximate statistics are out (spec 042); assembler emits exact
  per-trace models.
