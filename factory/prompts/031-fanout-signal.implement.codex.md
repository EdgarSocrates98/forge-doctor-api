You are implementing Loop Factory spec `031-fanout-signal`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\031-fanout-signal.md`
        Spec hash: `d5c6329cfaed3de22a8f169c317f5ce0f1c8d1e2a46f6808663c53c1cee92092`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

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

- Owner: project owner; decisions sourced from §59 and §119.
- Problem: a handler's dependency fan-out is a distinct signal — static
  call sites give a candidate count, traces confirm it. Today only
  `fanout_mean` baselines and `APIPERF007` regressions exist; there is no
  `FanoutSignal` model.
- Out of scope: capacity/cost aggregation (perf/capacity.py covers §92-93);
  retry amplification (RELAPI001/APIPERF004).
- Review failure: a FanoutSignal emitted with no evidence, or a static
  count presented as confirmed.
- Riskiest assumption: attributing client call sites to a specific handler —
  RESOLVED: static fanout is grouped per handler source file+line range;
  if attribution is ambiguous the signal records an UnknownFact.
- Smallest acceptable: `FanoutSignal` model + static candidate extraction
  + runtime confirmation + tests.

# Context

§59 defines `FanoutSignal` with two evidence tiers:

```text
static candidate:  handler calls 8 dependencies
runtime confirmed: trace shows 8 downstream spans
```

Existing primitives: `scan_clients` yields call sites (path+line);
framework route scans (`FastApiAdapter`) yield handlers (file+line);
`RequestExecution.downstream_calls` gives per-request fan-out.

# Acceptance Criteria

- `FanoutSignal` model: `subject` (operation/handler identity),
  `static_width` (int | None), `runtime_width` (int | None),
  `status` (CANDIDATE | CONFIRMED), `evidence`, `unknowns`.
- Static tier: count distinct outbound call targets in a handler's source
  span (same file; lines within the handler's region). Ambiguous region →
  width `None` + UnknownFact — never guessed.
- Runtime tier: distinct callee services/routes across executions of the
  operation → `runtime_width`; when a static count exists too →
  `CONFIRMED`, else runtime-only is still `CONFIRMED` (runtime evidence
  outranks static per §102).
- Both tiers absent → signal still emitted as `CANDIDATE` with `None`
  widths only when the caller asked for that subject — no phantom rows.
- Deterministic ordering by subject; serialization via `to_dict()`.
- Tests: static-only, runtime-only, both, ambiguous attribution, empty
  inputs; pytest/ruff/mypy pass.

# Constraints

- Evidence-first: every width carries its evidence tuple.
- UNKNOWN-confidence findings never block gates (§178 consistency).
- Offline: no new dependencies.
