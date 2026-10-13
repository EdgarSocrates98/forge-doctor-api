---
id: 072-cli-contract-stability
title: CLI/docs contract stabilization — inventory, stability levels, golden help
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
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
