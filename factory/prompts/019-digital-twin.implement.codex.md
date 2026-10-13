You are implementing Loop Factory spec `019-digital-twin`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\019-digital-twin.md`
        Spec hash: `e3a79b00b4097ef61d3f55d04bec768fc031be146fb509db1c0021e8834147bc`

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

- Owner: project owner; decisions sourced from §63, §64, §113.
- Problem: unify desired/declared/implemented/observed/hypothetical state into one queryable twin.
- Out of scope: twin-based what-if execution (experiment engine 016 produces HYPOTHETICAL inputs), fleet aggregation (025).
- Review failure: states conflated (e.g. declared treated as observed), twin drift asserted without per-state evidence.
- Riskiest assumption: twin is a *view* over existing models vs a new storage layer — RESOLVED: view/projection over ServiceGraph + upstream models; no duplicated state (per Constraints). History snapshots store compact normalized references, not raw payloads (§172).
- Smallest acceptable: five-state assembly + twin-drift classification + twin history recording.

# Context

`API Digital Twin` (§63) has five states: DESIRED (contracts, platform policies, SLOs), DECLARED (OpenAPI/AsyncAPI/gateway config/IaC), IMPLEMENTED (source routes, handlers, clients), OBSERVED (logs, traces, runtime metadata), HYPOTHETICAL (what-if/migration/contract change). Twin drift types (§64): CONTRACT_DRIFT, AUTH_DRIFT, ROUTING_DRIFT, VERSION_DRIFT, RUNTIME_DRIFT, SLO_DRIFT, DEPENDENCY_DRIFT. Twin history (§113) records contract/implementation/runtime/client state over time.

# Acceptance Criteria

- `ApiDigitalTwin` assembles the five §63 states from existing models (specs 003–018 outputs) — each state backed by its evidence sources, missing states → UNKNOWN.
- Twin drift detection per §64 types, each drift finding citing which states disagree and the evidence on both sides.
- `ApiTwinHistory` (§113): versioned snapshots of contract/implementation/runtime/client state; compact normalized storage (§172).
- Hypothetical-state ingestion: accepts experiment/migration scenarios as input without mutating observed states.
- Tests per §202 incl. partial-state twins (only some planes present).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- States never borrow each other's confidence — OBSERVED ≠ DECLARED.
- No duplicate storage of source models; twin references/views them.
- Drift findings distinguish which pair of states diverges.

# Review Notes

- Verify HYPOTHETICAL can never contaminate OBSERVED queries.
- Confirm history snapshots are compact (no raw payloads).
