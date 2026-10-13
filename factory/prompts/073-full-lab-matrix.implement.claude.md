You are implementing Loop Factory spec `073-full-lab-matrix`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\073-full-lab-matrix.md`
        Spec hash: `6c556863b7c7be9c3aa27f47ab5e91890e6ed44fe07d74be4d191aa71c931b02`

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

- Owner: project owner; decisions from stabilization prompt Phase C.
- Problem: "full corpus green" is a lie when extras are absent — the
  corpus silently loses coverage and reports confidence it did not earn.
- Out of scope: changing precision/recall math; adding scenario kinds.
- Review failure: skipped scenarios inflating pass-rate; a minimal
  install still reporting "43/43" style claims.
- Riskiest assumption: runners can always tell "unsupported" from
  "absent extra" — RESOLVED: `requires_extras` is declared ground truth;
  absence → skipped; presence + wrong output → failed as before.
- Smallest acceptable: skip-aware report + metrics split + CLI surface
  + tests covering minimal and full expectation.

# Context

Phase C continuation of 071. The lab is the evidence engine; its
metrics must distinguish "supported and passing", "supported and
failing", "unsupported (extra missing)", and "skipped by domain".

# Acceptance Criteria

- `LabReport` gains `skipped` count + `skipped_results`; `to_dict`
  carries per-scenario `skipped`/`skip_reason`.
- Run records persist the extras present at run time (detected via
  `importlib.util.find_spec`, sorted).
- CLI `lab` prints `skipped (missing extras)` rows and a summary line
  splitting passed/failed/skipped; `--require-extras` style flag not
  needed — report states the install profile instead.
- `test_lab.py` gains: minimal-profile corpus run yields
  `graphql/*` scenarios skipped with reason; full-profile run green;
  metrics split asserted in run record schema.
- pytest/ruff/mypy pass.
