# PyPI patch plan — forge-doctor-api

Cycle 11.2 (P1-004 + P1-006). Prepared for maintainer approval; nothing here
publishes, tags or uploads anything.

**RC-window note (`docs/rc-discipline.md`):** this change is metadata-only —
no runtime dependency, public surface, CLI or contract change. It falls under
"release fixes / docs corrections". The **version bump itself stays
forbidden** until the owner records a rationale in `docs/versioning.md`
(`version_gate.py` enforces it) — the proposal below is for the maintainer to
execute, not for this PR.

## Current state (audited in cycle 11.2)

| Signal | Value |
|---|---|
| PyPI published | `forge-doctor-api 0.2.0` (only release) |
| `pyproject.toml` | `0.2.0` — aligned |
| Git tag / GitHub release | `v0.2.0` — aligned |
| `requires-python` | `>=3.11` |
| CI matrix (`quality.yml`) | 3.11 / 3.12 / 3.13 — matches declared floor through latest tested |
| Published `project_urls` | **empty** — the 0.2.0 wheel predates the `[project.urls]` block |
| Published license | legacy `License: MIT` field; no `License-Expression` |

**No version drift**: PyPI = pyproject = tag = GitHub release.

## What changes in this PR

1. **`license = "MIT"`** (PEP 639 SPDX string) replacing
   `license = { text = "MIT" }`, and the now-redundant
   `License :: OSI Approved :: MIT License` classifier removed — PyPI rejects
   license classifiers combined with a `License-Expression`. This matches the
   sibling `forge-doctor-data`, which already publishes
   `License-Expression: MIT` via the same `poetry-core>=2.0` backend.
2. Classifiers already declare exactly the tested range (3.11–3.13);
   `project.urls` already complete and all targets exist.

Not changed: version (owner rationale required), CI matrix (no gap per
cycle-11.2 audit; 3.14 is inside `>=3.11` but untested — candidate for the
next cycle).

## Proposed next release: `0.2.1` (patch)

Rationale to record in `docs/versioning.md` before bumping (required by
`AGENTS.md` + `version_gate.py`): packaging-metadata correction
(SPDX license expression) — no runtime or contract change, additive-only
under RC.

### Provenance checklist for the maintainer

- [ ] Owner records the `0.2.1` rationale in `docs/versioning.md`.
- [ ] `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src`,
      `python -m build`, `forge-doctor-api lab` all green.
- [ ] `factory/rc_baseline.py --check` and `factory/sbom.py --check` green
      (license field is not part of the baseline; verified).
- [ ] Tag `v0.2.1`; publish via `publish-pypi.yml`.
- [ ] Verify PyPI shows `License-Expression: MIT` and populated
      project URLs.

## Local smoke evidence (this PR)

- Interpreters: system `python3.12` (3.12.3); uv-managed 3.11.16, 3.13.15,
  3.14.7 available locally.
- `python -m build` produces wheel + sdist; `forge-doctor-api --help` smoke
  OK on the available interpreters.

## Blockers

None.
