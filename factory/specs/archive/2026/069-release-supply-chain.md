---
id: 069-release-supply-chain
title: Release + supply chain — versioning policy, SBOM, provenance, release workflow
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m build
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §101-§103 +
  §10 leftovers (dependency review, release policy, SBOM, hashes,
  provenance, attestations).
- Problem: no release policy, no SBOM, no artifact hashes/provenance,
  no release workflow — §101-103 plus the §10 checklist items not
  covered by spec 035.
- Out of scope: actual publishing (a release workflow exists +
  dry-run path; `publish` stays a manual owner action); signing keys
  (provenance via GitHub OIDC attestations where available — else
  document the manual path).
- Review failure: a workflow that publishes on every tag without a
  gate; SBOM listing dev deps as runtime deps; hash docs claiming a
  scheme not implemented.
- Riskiest assumption: attestations without keys — RESOLVED: use
  `actions/attest-build-provenance` in the release workflow (OIDC,
  no keys in repo); document that attestations verify on GitHub-
  built artifacts only.
- Smallest acceptable: docs/release-policy.md (semver rules, what
  bumps what), release.yml (tag-gated build → wheel/sdist → SBOM
  via stdlib generator → sha256sums → attestation → GitHub release
  draft), dependency-review action in quality CI, SBOM generation
  test.

# Context

§101-§103 + §10: release policy, SBOM, artifact hashes, provenance,
attestations, dependency review.

# Acceptance Criteria

- `docs/release-policy.md`: version scheme, public-surface change →
  version rule table, release checklist (lab + benchmarks + docs
  contract green).
- `factory/sbom.py`: stdlib generator emitting CycloneDX-1.5 JSON
  {components: runtime deps from pyproject + transitive none
  declared} + test validating structure.
- `.github/workflows/release.yml`: workflow_dispatch + tag `v*`
  gated; build → sbom → `sha256sum` artifacts → attest → release
  *draft* (never auto-publish).
- quality.yml gains `dependency-review-action` on PRs.
- pytest/ruff/mypy/build pass.

# Constraints

- No keys/secrets in repo; OIDC attestation only.
- Release stays a draft — human publishes.
