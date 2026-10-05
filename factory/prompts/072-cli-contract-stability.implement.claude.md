You are implementing Loop Factory spec `072-cli-contract-stability`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\072-cli-contract-stability.md`
        Spec hash: `de4bdb06d61435f51e4ad4b027971db89f3adc29765cf84a92261c398f3e44b4`

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

- Owner: project owner; decisions from stabilization prompt Phase B.
- Problem: docs-as-contract (spec 068) checks command presence only;
  options can drift undocumented, and stability claims (stable vs
  experimental) are unwritten.
- Out of scope: renaming commands; deprecating anything already public
  without an owner decision.
- Review failure: a snapshot mechanism that is TTY/locale dependent;
  drift test that only checks a subset silently.
- Riskiest assumption: golden help snapshots are brittle across rich
  versions — RESOLVED: normalize (ANSI strip + fixed COLUMNS + line
  fold) before comparing, so snapshots pin *content*, not rendering.
- Smallest acceptable: machine-readable command inventory in
  `cli/catalog.py` (or tests-side walker) + option-level docs drift
  test + `STABLE`/`EXPERIMENTAL`/`DEPRECATED` registry + normalized
  golden help snapshots for every public command.

# Context

Phase B. The CLI is the public contract; `diff --semantic` and
`diagnose --before` must stay part of it (Case A — options exist and
are load-bearing; the failure was rendering, not the contract).

# Acceptance Criteria

- `cli/catalog.py` exposes `command_inventory()` → sorted
  `(path, options, arguments)` tuples walked from the Typer tree.
- `tests/test_cli_contract.py`: every STABLE command's documented
  options appear in `docs/cli.md`; every documented option exists in
  the inventory; undocumented options on STABLE commands fail the
  drift test.
- `cli/stability.py` (or catalog field) marks each top-level command
  STABLE | EXPERIMENTAL | DEPRECATED; `docs/cli.md` renders the level
  next to each command; drift between registry and docs fails.
- `tests/golden/cli/*.txt`: ANSI-free, width-normalized `--help`
  snapshot per public command; `tests/test_cli_snapshots.py` compares
  normalized output; regeneration via `python tests/golden/_regen.py`
  (documented, deterministic).
- `--semantic` on `diff` and `--before` on `diagnose` asserted present
  in inventory and docs.
- pytest/ruff/mypy pass.

# Constraints

- Snapshots normalize through one helper — no ANSI, fixed width,
  trailing-whitespace stripped; they must pass under rich 13 and 15.
