You are implementing Loop Factory spec `091-post-rc-discipline`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\091-post-rc-discipline.md`
        Spec hash: `084480f437fe495d3108c6f8e20c03fd9ce94c14b4803867fe0626f2aa6932fd`

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

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 11 and items §28/§31/§32.
- Problem: hardening programs end with a docs-shaped promise nobody
  enforces. The prompt requires an RC-discipline doc (what may and
  may not change during the RC window), the factory run record for
  this wave, and the final report artifact covering the prompt's
  §32 inventory.
- Out of scope: new gates beyond what earlier specs installed;
  the RC window schedule itself (owner decides timing); the
  release.
- Review failure: a discipline doc that is aspirational prose
  instead of enforceable rules; a final report claiming metrics
  that were never measured; missing known-limitations section.
- Riskiest assumption: the report's numbers drift from reality —
  RESOLVED: every number in the report is produced by a runnable
  command or a committed artifact, and the doc says which.
- Smallest acceptable: `docs/rc-discipline.md`, the dated run
  record under `factory/runs/`, and `docs/rc-final-report.md`
  covering every §32 field with real measured values.

# Context

Phase 11. Existing: `docs/rc-policy.md` (spec 081) defines the
stability classes; `factory/runs/` holds run records;
`docs/release-evidence.md` holds the stabilization matrix.
Missing: the discipline rules binding during RC, the program run
record, the final measured report.

# Acceptance Criteria

- `docs/rc-discipline.md`: what is allowed during the RC window
  (fixes, docs corrections, test additions, additive `x-*`
  extensions) vs forbidden (public-surface changes, contract-major
  churn, new plugin trust classes, dependency additions, breaking
  CLI changes); who approves exceptions; what ends the window.
- `factory/runs/2026-10-05-api-rc-hardening.md`: per-spec row —
  spec id, status, commit, verification commands run, result,
  known gaps. Written from `git log` + actual runs, not planned
  values.
- `docs/rc-final-report.md` covering §32 exactly: initial HEAD;
  final HEAD; tests before/after; CI matrix; lab metrics; real
  OSS corpus before/after + framework/protocol diversity; contract
  conformance state; cross-doctor fixtures; x-forge-api registry;
  MCP hardening; plugin boundary hardening; runtime benchmark
  curves + memory curves + snapshot scale; compatibility rule
  improvements; security/reliability precision changes; release
  artifact set; versioning decision; known limitations; next
  blockers. Each metric names its source (command or file).
- `AGENTS.md` updated if the wave changed pinned facts (version
  line, new hard rules added by this program).
- `docs/index.md` links the new RC docs.
- pytest/ruff pass.

# Constraints

- Report facts must be reproducible — cite the command or artifact
  for each number.
- Known limitations are listed honestly, not minimized.
- The discipline doc binds the RC window; it does not rewrite
  release policy.
