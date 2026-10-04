---
id: 035-quality-ci
title: Quality CI workflow + repository hygiene + contract inspect implementation
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m build
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §6-§10 (TRUST
  THE DOCTOR), §97, §10.
- Problem: only the self-scan workflow exists; there is no independent
  CI proving pytest/ruff/mypy/build on a matrix, no wheel/CLI smoke,
  no lab run, no offline/determinism proof in CI. `contract inspect`
  is a public stub (§9). SECURITY.md/Dependabot/CODEOWNERS absent (§10).
- Out of scope: publishing, release automation, signed attestations
  (spec 069); a second workflow for release.
- Review failure: CI that duplicates the self-scan instead of proving
  quality gates; a placeholder SECURITY.md; `contract inspect` left as
  a stub or removed without replacement.
- Riskiest assumption: `contract inspect` semantics — RESOLVED: render
  the contract metadata surface already produced by
  `load_openapi_project` (documents, versions, operations, schemas,
  unresolved refs) — never raw bodies.
- Smallest acceptable: quality.yml (matrix 3.11-3.13, pytest, ruff,
  mypy, build, wheel+CLI smoke, lab, offline test), SECURITY.md,
  CODEOWNERS, dependabot (pip+github-actions weekly), working
  `contract inspect`.

# Context

§6-§10. The self-scan gate (doctor-scan.yml) proves the tool's gate
works; it does not prove the repo is healthy. Quality CI must run the
same gates AGENTS.md documents plus wheel install + CLI smoke + lab +
offline hermetic proof. §9: no public placeholder commands.

# Acceptance Criteria

- `.github/workflows/quality.yml`: push→main, pull_request,
  workflow_dispatch; matrix Python 3.11/3.12/3.13 on ubuntu-latest.
- Steps: install (pip install -e . + dev deps), `python -m pytest -q`,
  `python -m ruff check .`, `python -m mypy src`, `python -m build`,
  wheel install smoke (install wheel into venv, `forge-doctor-api
  --version`), CLI smoke (`forge-doctor-api scan` on a lab fixture
  dir), `forge-doctor-api lab --no-record`.
- Single-Python determinism + offline job allowed to reuse the matrix
  job's steps (pytest already covers both via test_offline.py).
- `contract inspect <target>` implemented: prints documents (path,
  format, openapi_version, title, api_version, status), operation
  count + list (method, path, operation_id, deprecated), schema names,
  server urls, unresolved external refs; `--json` supported; exit 2 on
  unreadable input; never emits schema payloads.
- SECURITY.md (supported-version + reporting policy), CODEOWNERS
  (`* @EdgarSocrates98`), `.github/dependabot.yml` (pip + github-actions,
  weekly), CONTRIBUTING section or file pointing at AGENTS.md commands.
- No new runtime dependencies; pytest/ruff/mypy/build pass.

# Constraints

- YAML must be valid and minimal; no marketplace actions beyond
  actions/checkout, actions/setup-python (pin to major only).
- Console output deterministic (sorted), same style as existing CLI.
