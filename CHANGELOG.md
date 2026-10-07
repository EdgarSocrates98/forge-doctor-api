# Changelog

All notable changes to `forge-doctor-api` are recorded here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
entries are grouped by factory spec wave and dated by git history —
this file records what shipped, not what was planned.

The package is `0.2.0` and unreleased. See
[docs/versioning.md](docs/versioning.md) for the version decision
record, [docs/release.md](docs/release.md) for release mechanics,
and [docs/release-evidence.md](docs/release-evidence.md) for the
verification matrix.

## [0.2.0] — Unreleased

### RC-hardening program — 2026-10-06

- **Version marker**: `0.1.0` → `0.2.0`, owner-authorized to mark the
  "Trusted Unified Doctor" phase — wire contract frozen
  (`forge-contracts/1`), boundary proven, still no `1.0` commitment.
  Rationale: [docs/versioning.md](docs/versioning.md).
- **RC baseline freeze** (spec 081): `docs/rc-policy.md`,
  `docs/public-surface.md` stability tiers, `docs/rc-baseline.json`
  + `factory/rc_baseline.py --check` drift gate in CI.
- **Cross-doctor conformance** (spec 082): canonical `forge-contracts/1`
  fixtures, `x-forge-api` extension registry gate, shared extraction
  contract doc.
- **MCP boundary** (spec 083): error-matrix + stable error codes,
  tool inventory freeze (`mcp-inventory.json`), bounded payload tests,
  malformed-stdio resilience, `factory/mcp_smoke.py` wheel smoke.
- **Plugin trust** (spec 084): AST no-import gate, failure matrix,
  result-shape validation, no-network/no-mutation proofs.
- **OSS corpus depth** (spec 085): 31 vendored real-world slices with
  pinned provenance across 14 domains, 14 negative cases, per-domain
  precision/recall, multi-repo workspace lab scenario.
- **Runtime scale** (spec 086): 10k-endpoint / 100k-span recorded
  envelope with churn + snapshot tiers; assembler edge cases
  (duplicate span ids, cycles, tombstone overflow); heterogeneous
  `tuple` snapshot decode fix.
- **Contract compatibility** (spec 087): OpenAPI nullable/discriminator
  diffs, GraphQL union/directive changes, gRPC enum renumbering +
  oneof moves, new AsyncAPI compat engine (`ASYNC009–017`), client
  extractors for Feign/gRPC stubs/generated clients/GraphQL docs,
  adversarial compat matrix.
- **Security/reliability adversarial** (spec 088): middleware authz
  evidence (`AuthorizationPolicy.via`), gateway prefix/path scope
  binding, unresolved-scheme honesty (APISEC011 owns ambiguity,
  APISEC013 no longer fabricates breaks), non-evidence key skip in
  config walkers, cache graph partition guards + unknown propagation.
- **RC pipeline** (spec 089): `release_manifest.py`, `provenance.py`
  (in-toto-lite), `version_gate.py`, `self_scan.py` dogfood baseline
  (826 findings / 33 unknowns), `release_smoke.py` clean-venv wheel
  proof incl. MCP stdio handshake — all wired into CI.
- **Docs-as-contract expansion** (spec 090): README command catalog,
  release reproduction commands, MCP tool-name inventory match,
  contract-example parsing; readiness scorecard and test-pyramid docs.

## [0.1.0] — Unreleased

### Stabilization program — 2026-10-05

- **Wire contract** (spec 074): vendored `forge-contracts/1` models,
  schemas, validator, and adapters; canonical fixture + conformance
  tests prove the handoff surface speaks the shared wire language.
- **Boundary hardening** (spec 075): package-wide AST purity
  enforcement in `src/`; slim `ForgeRequest` (capabilities,
  context refs, delta); bounded handoff bundles with deterministic
  truncation and explicit unknowns; first-class `DeltaContext` fields.
- **Runtime/scale proof** (spec 076): streaming bounds, memory-growth
  evidence, tombstone semantics, snapshot format versioning, and
  `factory/benchmarks/scale_benchmark.py --check` enforced in CI.
- **Real-world corpus** (spec 077): vendored OSS slices (OpenAPI,
  AsyncAPI, GraphQL, gRPC) with `PROVENANCE.yaml` + SHA-256 pinning,
  seven negative cases, `labs/oss/` integration, `docs/corpus.md`.
- **Framework depth** (spec 078): FastAPI/Spring/Express/NestJS
  capability surfaces — auth, dependencies, error handlers, schemas,
  validation — with explicit unknowns for absent evidence and a
  `frameworks` lab pipeline; `docs/frameworks.md`.
- **Security/reliability precision** (spec 079): `AuthChainLink`
  records and `APISEC013` chain-break findings; `RELAPI008`
  mutation-idempotency check incl. `x-idempotent`/`x-idempotency-key`
  contract evidence; Kong/Istio/Envoy retry & timeout parsing;
  gateway/mesh config folded into edge-scoped reliability policies;
  header-only cache evidence emits explicit unknowns; `APICACHE003`
  shared-key writer/reader conflicts; `docs/security-reliability.md`.
- **Release maturity** (spec 080): this changelog,
  `factory/sbom.py --check`, `factory/sha256sums.py` emit/verify,
  release evidence record, quality-gate wiring.

### Stabilization program — 2026-10-04

- **Install matrix** (specs 071 + 073): lab scenarios declare
  `requires_extras`/`requires_domains` and skip with reason on
  minimal installs; help tests assert on canonicalized output;
  quality CI splits minimal (3.11) from full (3.11/3.12/3.13)
  profiles with a wheel-install smoke and graceful-degradation proof.
- **CLI contract stability** (spec 072): command inventory +
  stability registry in `cli/catalog.py`, canonical golden help
  snapshots, `docs/cli.md` stability markers, docs↔CLI drift tests.

### passo-1 build-out — 2026-10-03 → 2026-10-04

Specs 001–070 established the platform in dated waves (see
`factory/specs/archive/` for acceptance evidence):

- **Foundations** (001–009): core models, evidence/finding contracts,
  service graph, OpenAPI model + OAS001–020 checks, framework route
  discovery, contract drift, compatibility engine, client impact.
- **Surface analyzers** (010–019): API versioning, AsyncAPI, GraphQL,
  gRPC/proto, runtime evidence, request execution, performance,
  reliability, security, digital twin.
- **Intelligence layer** (020–029): change intelligence, diagnose,
  safe-fix, policy engine, workspace, fleet, Forge Lab, knowledge
  packs, migration, handoff.
- **Unified engine** (030–040): release stabilization, fanout signal,
  gateway/mesh model, IaC/Kubernetes, cache model, quality CI,
  deterministic gate, artifact discovery, analysis plan, doctor
  report, unified scan.
- **Runtime 2.0 + integrations** (041–054): bounded streaming +
  aggregation + benchmark, public SDK, MCP server, Forge protocol,
  Handoff V2, context refs, delta support, framework adapters,
  plugin registry/conformance.
- **Depth + output contract** (055–070): depth intelligence,
  realworld lab, incremental engine, stats/explain, output contract
  v1, docs-as-contract, release workflow, boundary surface.
