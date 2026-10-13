---
id: 089-release-candidate-pipeline
title: RC pipeline — release manifest, provenance, dirty-tree policy, version gate, release smoke
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m build
---

# Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 9 and items §21/§22/§23.
- Problem: release plumbing exists (build, sbom --check,
  sha256sums, attest workflow) but the RC artifact set lacks a
  machine-checkable release manifest, a recorded provenance
  document, a dirty-tree policy, a version-consistency gate, and a
  runnable release smoke that installs the wheel and exercises
  CLI/contract/lab/MCP.
- Out of scope: actually publishing (no PyPI, no tag push — draft
  release workflow stays human-gated); Sigstore changes (workflow
  already attests); dependency additions.
- Review failure: a manifest that's a copy of sbom data instead of
  a *release* manifest (versions, hashes, contract family, python
  matrix, artifact digests); provenance that isn't regenerated
  deterministically; a smoke script that skips the wheel path.
- Riskiest assumption: version mismatch detection needs cross-
  file truth — RESOLVED: the gate reads pyproject, `__init__`
  `__version__`, `sdk.SDK_VERSION`, and the built wheel/sdist
  filenames and fails on any divergence.
- Smallest acceptable: release-manifest.json generator + check,
  provenance.json generator, dirty-tree policy in the generator,
  version gate test, release_smoke.py, dogfood self-scan baseline,
  docs.

# Context

Phase 9. Existing: `factory/sbom.py`, `factory/sha256sums.py`,
`factory/release_evidence.py`-equivalent doc, `.github/workflows/
release.yml` (attestation + draft release), quality.yml wheel smoke,
`factory/runs/doctor-self-scan-v0.1.json` baseline. Missing:
release manifest, provenance file, dirty policy, version gate,
release smoke, self-scan gate wiring.

# Acceptance Criteria

- `factory/release_manifest.py` emits `release-manifest.json`:
  version, git HEAD (or recorded HEAD when generated outside git),
  dirty-tree flag, python_requires + classified versions, contract
  family/version, Forge protocol version, artifact filenames +
  sha256 digests, schema ids list, CLI command count, MCP tool
  count. `--check` regenerates + diffs.
- `factory/provenance.py` emits `provenance.json` (in-toto-lite):
  builder id (local/CI), source repo, revision, build commands,
  artifact digests, tool versions; deterministic ordering.
- Dirty-tree policy: generator refuses to mark an artifact
  `rc: true` when the tree is dirty unless `--allow-dirty` is
  passed; test covers both paths.
- Version-consistency gate: a test/script fails when
  `pyproject.version`, `__version__`, `SDK_VERSION`, and the
  built dist filenames diverge; also checks `release-manifest.json`
  `version` field.
- `factory/release_smoke.py`: from a clean venv install of the
  built wheel — `forge-doctor-api --help`, `scan` on a fixture
  project, `contract inspect`, `lab --no-record` subset, MCP
  initialize via `factory/mcp_smoke.py` when extras installed.
  Wired into quality.yml full job.
- Dogfood gate: `factory/self_scan.py --check` diffs the self-scan
  report against `factory/runs/doctor-self-scan-v0.1.json`
  baseline shape (allowing expected drift only in whitelisted
  volatile fields); CI step in the full job.
- `docs/release.md` extended: RC artifact set list, reproduction
  commands, dirty-tree policy, version gate, supply-chain +
  private-repo dependency review note (item §22 — no vendored
  third-party code paths, declared deps only).
- pytest/ruff/build pass; manifest+provenance regenerate
  deterministically.

# Constraints

- All factory scripts stdlib-only; CI steps run in existing jobs
  (no new workflow files unless a job cannot host the step).
- Release smoke must run against the *wheel*, not the source tree.
- Manifest schema is additive/evolvable: `manifest_version: 1`.
