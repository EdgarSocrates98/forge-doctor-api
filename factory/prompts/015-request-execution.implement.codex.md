You are implementing Loop Factory spec `015-request-execution`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\015-request-execution.md`
        Spec hash: `6ff9f11231d55978351cc9ca4d4f62e5cdfd06326abf77adc101e1183952b68b`

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

- Owner: project owner; decisions sourced from §28, §29, §87.
- Problem: the API-native `QueryExecution` equivalent — normalized per-request records that baselines/regressions consume (§4 evidence plane).
- Out of scope: baseline computation and regression detection (016), artifact parsing (014 produces inputs).
- Review failure: lossy normalization (dropped retries/downstream data), nondeterministic history ordering.
- Riskiest assumption: field set covers needed runtime signals — mitigate by keeping `evidence` refs to raw summaries.
- Smallest acceptable: the three models + normalization from spec 014 output + compact history storage.

# Context

`RequestExecution` (§28): request_id, trace_id, service, operation, method, route, start, duration, status, request_bytes, response_bytes, retries, downstream_calls, cache_status, evidence. `DownstreamCall` (§29): caller, callee, operation, duration, status, timeout, retries, protocol. `RequestHistory` (§87) stores compact normalized history — summaries only, no full raw retention (§172–§173).

# Acceptance Criteria

- `RequestExecution` model per §28 — all fields, `evidence` provenance required.
- `DownstreamCall` model per §29; executions link to their downstream calls (1:N).
- Normalizer converts `TraceModel`/access-log summaries (spec 014) into `RequestExecution` + `DownstreamCall` records; unmatched/missing fields → UNKNOWN, never fabricated.
- `RequestHistory` (§87): compact append/query storage keyed by service+operation+window; deterministic ordering; summary-level only (§172–§173).
- Graph materialization where derivable: CALLS/RETRIES edges from observed traffic marked `RUNTIME`/`OBSERVED_METADATA` evidence.
- Tests per §202 incl. determinism and large-volume handling.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- No inferred fields — missing data stays UNKNOWN (§1).
- Storage stays compact/normalized; no raw trace bodies (§173).
- Read-only over spec 014 outputs.

# Review Notes

- Check retry-count semantics: observed retries vs configured policy — keep them distinct fields/sources.
- Confirm history compaction doesn't lose the ability to answer "what changed" queries later.
