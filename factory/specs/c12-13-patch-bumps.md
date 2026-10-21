---
id: c12-13-patch-bumps
title: Patch bumps 0.2.3/0.2.4/0.2.5 during RC window (owner-authorized)
agent: devin
risk: low
grill: delegated-to-owner-pr-review
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m build
---

# RC Exception Record

This spec is the `factory/specs/` entry `docs/rc-discipline.md` requires
for deviations merged during the RC window. The bumps are
owner-authorized patch releases; `docs/versioning.md` carries the
recorded rationale for each (`0.2.3`, `0.2.4`, `0.2.5`), satisfying the
"rationale is the artifact" rule. Tags `v0.2.3`–`v0.2.5` were pushed
under the same owner directive that lifted the publish/tag hold for the
`0.2.x` patch line (see the `0.2.1` decision).

- What shipped: 0.2.3 — wheel-first portable distribution
  (`_data/labs` packaged corpus, `lab/packaged.py`, `--dist`/`--allow-url`
  bootstrap modes, smoke-before-register). 0.2.4 — `install.windows.sh`
  Git Bash route + `bash -n` CI gate, wheel-over-editable defaults.
  0.2.5 — re-vendored hardened Graph Studio + portal explorer assets.
- What does not change: public-surface contracts, wire schemas, runtime
  dependencies, check ids, MCP tool inventory — patch band only.
- Coverage added post-review: `tests/test_forge_bootstrap.py` exercises
  the new install surface (redaction, PEP503 gate, `--allow-url`,
  provenance, `managed_files`, `FORGE_PYTHON`); `test_artifact_contents`
  retries `--no-isolation` so the wheel gate stays honest hermetically.
