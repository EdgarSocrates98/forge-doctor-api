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
