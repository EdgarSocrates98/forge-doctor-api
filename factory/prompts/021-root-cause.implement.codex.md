You are implementing Loop Factory spec `021-root-cause`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\021-root-cause.md`
        Spec hash: `96f114d9b3605893518c67f027fc0de13c042f2c6bdcd8fc5428250283335d96`

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
- `python -m forge_doctor_api diagnose --help`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from §60, §61, §62, §102, §103, §165, §166.
- Problem: promote correlated signals into honest candidate root causes — "candidate", not verdict.
- Out of scope: auto-remediation execution (022 classifies; nothing executes fixes), cross-domain handoff (029).
- Review failure: causality asserted beyond evidence hierarchy, single-candidate presented without unknowns, missing evidence trail.
- Riskiest assumption: evidence-hierarchy promotion rules — RESOLVED: a cause presents as DERIVED-correlated only when RUNTIME and STATIC/CONFIG evidence agree; STATIC-only or single-plane evidence stays candidate. Every promotion cites the chain; multiple candidates stay ranked by evidence tier.
- Smallest acceptable: `ApiIncidentEpisode`, cascading-failure path detection, `diagnose` + `explain` CLIs per §165–§166.

# Context

Cascading failure analysis (§60): e.g. payments latency → orders timeout → orders retry → payments load↑. `ApiIncidentEpisode` (§61) combines runtime regression + change event + service graph + SLO + retry topology. §62 gives the reference shape: symptom → path → change → observed → candidate cause. Root-cause promotion uses the evidence hierarchy (§102–§103): STATIC possible → RUNTIME observed → DERIVED confirmed. `diagnose` (§165) clusters findings into symptom/candidate root cause/affected services/evidence/unknowns; `explain <finding>` (§166).

# Acceptance Criteria

- `ApiIncidentEpisode` model (§61) joining runtime regressions (016), change events (020), service graph, SLO context, retry topology (017).
- Cascading-failure path extraction (§60): latency→timeout→retry→load chains across services, each hop evidenced.
- Root-cause promotion per §102–§103: findings promote only up the evidence hierarchy; STATIC-only candidates never present as confirmed; every promotion cites its evidence chain.
- `diagnose` CLI (§165) output groups: symptom, candidate root cause(s), affected services, evidence, unknowns — multiple candidates stay ranked, never collapsed.
- `explain <finding>` CLI (§166) renders evidence chain + classification reasoning for one finding.
- §62-style fixture reproducible: checkout p95 → payments → external PSP, timeout change → retry 4x → "candidate cause: timeout/retry policy change" with observed-stable latency noted.
- Tests per §202; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- Never assert unsupported causality (§227 wording discipline).
- Unknowns are always printed alongside candidates (§165).
- Diagnosis is read-only over prior specs' outputs.

# Review Notes

- Verify candidate ranking orders by evidence tier, not recency.
- Confirm `explain` never reveals redacted fields (§57/§125).
