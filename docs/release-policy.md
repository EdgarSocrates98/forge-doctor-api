# Release policy

## Versioning

- The package follows SemVer-shaped `MAJOR.MINOR.PATCH` (PEP 440).
- `0.x` line: MINOR may add features; PATCH is fixes only. Breaking
  changes to any public surface require a MINOR bump *and* a note in
  the changelog — the `0.x` line carries no stability promise, but
  breaks are never silent.
- Public surfaces tracked for breaking changes:
  - `forge_doctor_api` SDK exports (`__all__`, see `sdk.py`)
  - `DoctorReport` and every emitted `Model` shape
    ([output-contract.md](output-contract.md) v1 — additive only)
  - CLI command names, arguments, exit codes ([cli.md](cli.md))
  - `doctor://` URI forms and `doctor.*` MCP tool names
  - `ForgeRequest`/`ForgeHandoff`/`ForgeResult` protocol types
  - Check ids (`OAS001`, `APISEC011`, …) — id reuse with changed
    meaning is a break.
- Schema versions (`schema_version` in exports) bump independently of
  the package version: additive change ⇒ MINOR, break ⇒ MAJOR.

## Release checklist

1. All quality gates green on `main`:
   `pytest -q`, `ruff check .`, `mypy src`, `python -m build`,
   `forge-doctor-api lab --no-record`.
2. Changelog entry describing user-visible changes.
3. Version bump in `pyproject.toml` (no version bump without a
   release — main may sit on the last released version).
4. Tag `v<MAJOR.MINOR.PATCH>` — the release workflow triggers on
   `v*` tags or manual `workflow_dispatch`.
5. The workflow builds wheel + sdist, generates the CycloneDX SBOM
   (`factory/sbom.py`), SHA-256 sums, and a build-provenance
   attestation via GitHub OIDC, then opens a **draft** GitHub
   release.
6. A human reviews the draft and publishes — the workflow never
   auto-publishes.

## Supply-chain guarantees

- The SBOM declares exactly the dependencies `pyproject.toml`
  declares — required deps as `scope: required`, extras as
  `scope: optional`. No transitive or undeclared dependency is ever
  claimed.
- Artifacts carry `SHA256SUMS` and a Sigstore build-provenance
  attestation produced inside the release workflow's OIDC identity.
- `dependency-review-action` runs on every PR — a new runtime
  dependency is a policy-relevant change, reviewed like code.
- Untrusted plugin code is never imported anywhere in the release or
  runtime path ([ADR-0004](adr/ADR-0004-untrusted-plugins.md)).
