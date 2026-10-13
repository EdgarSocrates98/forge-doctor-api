You are implementing Loop Factory spec `071-ci-clean-install`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\071-ci-clean-install.md`
        Spec hash: `f02a7ea7ff97c34c29e4d09dc76e7bf9d1072465a119143f51d415e04552c909`

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

- Owner: project owner; decisions sourced from stabilization prompt §0-§2, Phase A.
- Problem: developer env (rich 13.x, extras installed) passes 1267 tests
  while clean CI (rich 15, no extras) fails 3 — environment drift is
  unbounded and invisible.
- Out of scope: changing the public CLI contract of diff/diagnose flags;
  matrix expansion beyond 3.11/3.12/3.13.
- Review failure: tests that only pass because the dev box has extras;
  help assertions that break under rich-15 narrow-width rendering again.
- Riskiest assumption: rich>=15 help truncation is the root cause —
  RESOLVED: reproduced; rich 15 folds long option rows at COLUMNS=80,
  splitting `--semantic`/`--before` across lines, so substring asserts
  die. Fix = normalized help capture (fixed COLUMNS + ANSI strip).
- Smallest acceptable: (a) ANSI-insensitive help assertions shared via a
  tests helper, (b) lab scenarios declare requires_extras and skip with
  an explicit reason when the extra is absent, (c) quality.yml gains a
  minimal + full split with wheel smoke on both, (d) documented
  clean-install commands in docs/development.md.

# Context

Phase A + Phase C of the stabilization program. `expected.yaml` gains
`requires_extras`/`requires_domains`; a scenario whose extras are
absent is `SKIPPED_WITH_REASON` — counted separately, never silently
omitted, never a failure. `lab` output and run records split
supported/unsupported/skipped-by-extra coverage. "Full corpus" only
means all required extras installed.

# Acceptance Criteria

- `LabScenario.requires_extras`/`requires_domains` parsed from
  `expected.yaml`; `LabResult` gains `skipped`/`skip_reason`.
- `run_labs` marks a scenario skipped (not failed) when its extras are
  absent; the lab CLI prints the skip reason; metrics separate
  supported vs skipped-by-extra vs unsupported.
- `graphql/unbounded-list` (and every graphql/mcp-dependent scenario)
  declares `requires_extras`; minimal install → skip-with-reason, full
  install → pass.
- Help tests assert against ANSI-stripped, fixed-width output via a
  shared `tests/cli_help.py` helper; `test_diff_semantic_help` and
  `test_diagnose_help` pass under rich 13 and rich 15.
- `.github/workflows/quality.yml`: minimal 3.11 job (no extras) +
  full 3.11/3.12/3.13 jobs (`.[graphql,mcp]`); wheel install smoke for
  both minimal and full.
- `docs/development.md` documents the exact clean-venv reproduction
  commands (venv → pip install -e → pytest/ruff/mypy/build).
- pytest/ruff/mypy pass locally with extras; the minimal path is
  provable without uninstalling (tests simulate absence via
  monkeypatched `importlib.util.find_spec`).

# Constraints

- No new runtime deps. Extras detection via `importlib.util.find_spec`
  only — never a real import in detection code.
- Sorted/deterministic output for skip lists.
