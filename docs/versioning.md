# Versioning

What a version number promises on this project, the recorded
`0.1.0` → `0.2.0` decision, and what would justify `1.0` later.

For mechanics (artifacts, gates, smoke) see
[release.md](release.md); for semver rules per surface see
[release-policy.md](release-policy.md).

## Why the version communicates trust stage

On this project the version is a *trust signal*, not a marketing
counter:

- **`0.x`** — no stability promise. Anything may change; every bump
  requires a documented rationale (this file) because the number
  itself is the record of which trust stage was reached.
- **Release candidate (RC)** — the package declares its public
  surface frozen: wire contract, CLI inventory, MCP tool set, check
  ids. From RC forward, changes to frozen surfaces are
  additive-only and breaking changes require the contract
  compatibility machinery, not silent edits.
- **`1.0`** — the stability promise is real: a downstream consumer
  has proven the wire contract works unchanged, so freezing it is
  honest rather than aspirational.

## The recorded decision — `0.2.0`

**Decision (owner-authorized): bump `0.1.0` → `0.2.0`.**

The bump marks the *Trusted Unified Doctor* phase:

- `forge-contracts/1` wire contract is vendored, validated, and
  conformance-tested against canonical fixtures
  (`tests/contracts_cross_doctor/`, `test_contract_conformance.py`).
- The plugin boundary is proven: AST import gate, result validation,
  no-network/no-mutation proofs (spec 084).
- The MCP boundary is proven: stable error matrix, frozen tool
  inventory, bounded payloads, malformed-input resilience
  (spec 083).
- Real-world evidence exists: 31 pinned OSS corpus slices,
  10k/100k runtime envelope, adversarial compat + security/
  reliability matrices (specs 085–088).
- The release pipeline is mechanical: manifest, provenance,
  version gate, self-scan, wheel smoke (spec 089).

`0.1.x` undersold that shipped surface; `1.0` would oversell it
(see triggers below). `0.2.0` is the honest marker. The standing
rule is preserved: **no bump without an owner-documented rationale
recorded in this file** — and no `1.0`, publish, or tag.

## The recorded decision — `0.2.1`

**Decision (owner-authorized, 2026-10-18): bump `0.2.0` → `0.2.1`.**

Patch bump under RC discipline (`0.2.x` band): no public-surface,
contract, or dependency changes. Ships only accumulated fixes on main —
vendored Forge Portal 2.1 final (Cycles 0-6: real telemetry, homologation,
personalization, security headers) and the self-scan baseline rebind that
tracks hashed bundle filenames. Owner directed the ecosystem-wide patch
release so published wheels carry the corrected portal. The same owner
directive authorized the PyPI publish and the `v0.2.1` tag — the
"no publish, or tag" hold recorded under `0.2.0` is lifted for this
patch only; `1.0` remains un-cut by the conditions below.

## The recorded decision — `0.2.2`

**Decision (owner-authorized, 2026-10-18): bump `0.2.1` → `0.2.2`.**

0.2.2 — patch: portal 2.2 vendored generation + hardened publish
pipeline; authorized patch bump. Under RC discipline (`0.2.x` band):
no public-surface, contract, or dependency changes — the release ships
the vendored Portal 2.2 generation (44-asset frontend, telemetry,
py3.10-safe server) and the hardened PyPI pipeline (build-once/
publish-same-artifact, version gate, post-publish verify).

## The recorded decision — `0.2.3`

**Decision (owner-authorized, 2026-10-20): bump `0.2.2` → `0.2.3`.**

Patch bump under RC discipline (`0.2.x` band): no public-surface,
contract, or dependency changes. Ships Cycle 12 wheel-first portable
distribution — the `labs` corpus packaged as `forge_doctor_api/_data`
(poetry `packages.to`) resolved via `lab/packaged.py` (the allowlisted
importlib.resources boundary), `lab` run-record redirect so packaged
installs never write into site-packages, and the `forge_bootstrap.py`
`--dist`/`--allow-url` install modes (PEP503 name-match, credential
userinfo redaction, checksum provenance A/B/C, `managed_files`
receipts, `FORGE_PYTHON`, smoke-before-register). Owner directed the
patch release so published wheels carry the portable corpus; the
`v0.2.3` tag rode the same directive as `v0.2.1`.

## The recorded decision — `0.2.4`

**Decision (owner-authorized, 2026-10-20): bump `0.2.3` → `0.2.4`.**

Patch bump under RC discipline (`0.2.x` band): no public-surface,
contract, or dependency changes. Ships Cycle 12.1 — the
`install.windows.sh` Git Bash/MSYS route plus its `bash -n` CI gate,
`install.sh`/`install.ps1` defaulting to wheel over `--editable`, and
the vendored bootstrap re-stamped to canonical ruff-formatted source.
`v0.2.4` tag under the same owner directive.

## The recorded decision — `0.2.5`

**Decision (owner-authorized, 2026-10-21): bump `0.2.4` → `0.2.5`.**

Patch bump under RC discipline (`0.2.x` band): no public-surface,
contract, or dependency changes. Ships Cycle 13 — the re-vendored
hardened Graph Studio (P0 physics NaN fix, scalable
overview/explore/full modes, CSP + nosniff headers, `unquote` fix,
GET-only loopback server) and post-lf-0023 portal explorer assets.
`v0.2.5` tag under the same owner directive.

## The recorded decision — `0.2.6`

**Decision (owner-authorized, 2026-10-21): bump `0.2.5` → `0.2.6`.**

Patch bump under RC discipline (`0.2.x` band): no public-surface,
contract, or dependency changes. Ships the integrations-cycle
review hardening — bootstrap test coverage (`test_forge_bootstrap`,
114 tests), `smoke()` FAIL-on-empty-stdout, `_explicit_python_argv`
trim fix, `redact_url_userinfo` raw-`@` userinfo fix, docs-contract
fence on portable-installation examples — plus the re-vendored
portal bundle carrying the Specialist/Delegation Explorer pages
(lf-0032). `v0.2.6` tag under the same owner directive.

## What justifies `1.0`

`1.0` is cut when **both** conditions hold:

1. A `forge-contracts/1` payload produced by this package is
   consumed *unchanged* by a downstream Data Doctor / Forger
   release — real interop proof, not synthetic conformance.
2. The CLI inventory and check catalog stay additive-only for a
   full release cycle — drift proven absent by `rc-baseline` and
   `docs-as-contract` gates.

Until then the `0.x` line stays honest: breaking changes ship as
`0.2.x` with changelog notes and compat findings.

## Stability promise per surface

| Surface | Tier | Proof |
| --- | --- | --- |
| `forge-contracts/1` wire payload | stable family | `contracts/` + canonical fixtures + conformance suite |
| `ForgeRequest` v2 / handoff | stable | bounded-bundle tests, `forge-protocol/2` |
| MCP `doctor.*` tools | stable | `factory/artifacts/mcp-inventory.json` freeze + drift gate |
| CLI commands (28) | stable | `cli/catalog.py` + `docs/cli.md` golden help |
| Check ids (catalog) | stable ids | `checks/catalog.py`; semantics may sharpen |
| Python SDK / module internals | experimental | not import-frozen; pin the version |
| Output formats | stable | `output/writers.py` + `docs/output-formats.md` |
| Lab / corpus / factory tooling | internal | not part of the shipped wheel contract |

## Rules for future bumps

- A bump lands only with an entry added here in the same commit —
  the rationale is the artifact, the number is the index.
- `version_gate` (`factory/version_gate.py`) keeps `pyproject.toml`,
  `__init__.__version__`, `SDK_VERSION`, the release manifest, and
  dist filenames in agreement — a partial bump fails the suite.
- Patch bumps (`0.2.x`) are for bug/FP/FN/docs fixes under RC
  discipline; MINOR bumps (`0.3.0`) require the same documented
  rationale this file records for `0.2.0`.

## The recorded decision — `0.2.7`

**Decision (owner-authorized): bump `0.2.6` → `0.2.7`.**

Patch under RC discipline — vendored installer hardening only; no
public-surface, contract or dependency change:

- `_installkit` v1.0.2 vendored (`_installkit.py` +
  `scripts/forge_installkit.py` in lockstep): `_URL_USERINFO_RE`
  `[^/@\s]+@` → `[^/\s]+@` — the old pattern truncated at the first
  `@` and leaked `user:pw` fragments in wheelhouse URLs; stale-lock
  `created_at` fallback for undecidable PIDs (Windows).
- `forge_bootstrap` v1.1.1: argv trim + empty-stdout smoke FAIL.
- The wheel ships `_installkit.py` (`test_package_carries_install_surface`
  asserts it), so the credential-redaction fix must be published —
  PyPI previously served v1.0.0 with the weak regex.
