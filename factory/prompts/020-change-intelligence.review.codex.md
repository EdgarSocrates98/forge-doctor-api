Review Loop Factory spec `020-change-intelligence` against current working tree.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\020-change-intelligence.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
- `python -m forge_doctor_api diff --semantic --help`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §65, §66, §67, §68, §179.
- Problem: turn diffs into typed change events that downstream engines (perf correlation, PR gate) consume.
- Out of scope: git-host API integration (PR intel works from diffs/exports), policy gating decisions (023/030 own `fail-on` config).
- Review failure: change types missed/duplicated, blast radius overstated beyond evidence, fingerprint instability across formatting.
- Riskiest assumption: `ChangeEvent` granularity — RESOLVED: operation+element level (endpoint/field/param/status/policy), not file level; downstream engines (blast radius, PR counters) need element resolution.
- Smallest acceptable: §65 change taxonomy + `diff --semantic` CLI + PR-intel summary + blast-radius chain + contract fingerprint baseline.

# Context

Semantic change types (§65): ENDPOINT_ADDED, ENDPOINT_REMOVED, METHOD_CHANGED, SCHEMA_CHANGED, AUTH_CHANGED, TIMEOUT_CHANGED, RETRY_CHANGED, RATE_LIMIT_CHANGED, DEPENDENCY_CHANGED, VERSION_CHANGED. `forge-doctor-api diff --semantic` (§66). PR intelligence (§67): counts of breaking changes, affected clients, new public endpoints, authz changes, SLO-relevant dependency changes, unknowns. Blast radius (§68): changed operation → clients → services → business paths. `BackwardCompatibilityBaseline` (§179) stores contract fingerprints for diff anchors.

# Acceptance Criteria

- `ChangeEvent` typed per §65 taxonomy, produced by the semantic diff (spec 008 machinery) with before/after detail + evidence.
- `diff --semantic` CLI per §66 producing structured change events (console + JSON).
- PR-intel summary generator per §67 format — all six counters incl. explicit `Unknowns`.
- `blast-radius` output per §68 chain (operation → clients → services → business paths where known); CLI `graph blast-radius` per §161.
- `BackwardCompatibilityBaseline` store keyed on semantic fingerprints (§179–§180).
- Tests per §202 incl. fingerprint stability across formatting/ordering/comments.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Change events are derived facts — every one traces to a diff element (DERIVED evidence).
- Blast radius lists only evidenced nodes; unknown propagation → UNKNOWN entries.
- No VCS/forge API calls — inputs are local diffs/contracts (§1).

# Review Notes

- Verify PR summary never drops the Unknowns counter (§67).
- Confirm TIMEOUT_CHANGED/RETRY_CHANGED pick up config-file diffs, not just contract diffs.
