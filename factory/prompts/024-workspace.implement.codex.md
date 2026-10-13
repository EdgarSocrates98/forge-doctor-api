You are implementing Loop Factory spec `024-workspace`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\024-workspace.md`
        Spec hash: `223bc8ac03e0858b0b12329881d53dd85862679b8ed4bdf33965067470cf8e99`

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

- Owner: project owner; decisions sourced from §108, §109.
- Problem: real API surfaces span repos — service repo, client repo, gateway repo, contracts repo must link.
- Out of scope: fleet-level analytics (025), VCS-provider integrations.
- Review failure: cross-repo edges asserted without declared links, workspace silently guessing repo roles.
- Riskiest assumption: workspace manifest format — RESOLVED: explicit `forge-doctor-api.workspace.yaml` declaring member repo roots + roles. Membership is declared only; no convention-based discovery, no parent-dir walking (§203).
- Smallest acceptable: `Workspace` model + manifest + per-repo scan assembly + cross-repo contract/client edges.

# Context

APIs cross repositories (§108): `Workspace` links service repo, client repo, gateway repo, contracts repo. Cross-repo chains (§109): e.g. payments-api repo → payments-sdk repo → checkout repo. This extends spec 009's basic client impact to multi-repo blast radius.

# Acceptance Criteria

- `Workspace` model: named member repos with declared roles (`service | client | gateway | contracts | mixed`), filesystem roots via `ProjectContext` (§203).
- Workspace manifest file defines members explicitly — no filesystem wandering to "discover" repos.
- Scan assembles per-repo models then links: cross-repo client→operation edges (extends §17 chain), contract repo → implementation repos, gateway repo → routed services.
- Cross-repo contract chain resolution per §109 (api → sdk → consumer), each hop evidenced.
- Blast radius and PR-intel outputs can express cross-repo impact; unknown linkage → UNKNOWN.
- Tests per §202 incl. missing member, role-ambiguous repo, broken chain.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Membership is declared, not discovered by walking parent dirs (§203 discipline).
- No network/VCS calls — local checkouts only (§1).
- Role of a repo is declared or UNKNOWN — never inferred from layout.

# Review Notes

- Verify a repo appearing in two roles is handled explicitly.
- Confirm cross-repo edges carry which repo each endpoint lives in (auditability).
