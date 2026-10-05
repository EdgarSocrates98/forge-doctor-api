---
id: 080-release-maturity
title: Release maturity — changelog, SBOM+SHA256SUMS, version decision, release evidence
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m build
  - python factory/sbom.py --check
---

# Grill Gate

- Owner: project owner; decisions from stabilization prompt Phase K.
- Problem: release artifacts are partial (factory/sbom.py exists,
  test_release.py exists) but there's no changelog discipline, no
  SHA256SUMS gate, and the version decision (stay 0.1.x per AGENTS.md
  hard rule) isn't recorded as a decision with evidence.
- Out of scope: publishing to PyPI; bumping to 1.0 (AGENTS.md forbids
  version bump — decision is recorded, not executed); signing.
- Review failure: changelog written as marketing copy instead of
  contract deltas; SBOM drifting from pyproject; SHA256SUMS that
  aren't reproducible from a clean build.
- Riskiest assumption: `--check` on sbom.py can't exist because the
  file has no manifest to check against — RESOLVED: check mode
  rebuilds the SBOM from pyproject and diffs against the committed
  artifact; drift = fail, same pattern as scale-benchmark baseline.
- Smallest acceptable: CHANGELOG.md seeded from archived specs
  (070-era) + this program's waves; sbom.py gains --check;
  SHA256SUMS generation + verification script; release-evidence doc
  recording the version decision and the full verification matrix.

# Context

Phase K. Existing: `factory/sbom.py` (CycloneDX 1.5 from pyproject),
`test_release.py`, `.github/workflows/` quality gate. Missing:
CHANGELOG.md, SHA256SUMS, sbom --check, release-evidence record.

# Acceptance Criteria

- `CHANGELOG.md` created — Keep-a-Changelog-ish, dated entries
  grouped by spec wave; initial backfill covers what the archive
  specs evidence (not invented history).
- `factory/sbom.py` gains `--check` (regenerate-and-diff against
  committed `dist/` artifact or `factory/artifacts/sbom.cdx.json`)
  and `--out` already exists.
- `factory/sha256sums.py` (new): builds wheel+sdist into dist/,
  emits `SHA256SUMS` deterministically sorted, `--verify` re-hashes
  and diffs.
- `factory/release_evidence.py` or `docs/release-evidence.md`:
  records initial HEAD, final HEAD, per-phase verification matrix,
  test counts before/after, minimal/full install matrix results.
- `docs/release.md` (new or extended): version decision recorded
  (0.1.x until the wire contract + boundary prove stable — the
  decision, not a date), artifact inventory, reproduction commands.
- Quality workflow runs sbom --check + sha256sums --verify in the
  full job.
- pytest/ruff/mypy/build pass.

# Constraints

- AGENTS.md hard rule: version stays 0.1.0. The decision record
  explains why, cites the wire-contract evidence, and names the
  trigger for revisiting.
- No new runtime deps; factory scripts are stdlib-only.
