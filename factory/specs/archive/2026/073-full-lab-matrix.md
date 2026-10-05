---
id: 073-full-lab-matrix
title: Full-lab capability matrix — supported/unsupported/skipped metrics
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
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
