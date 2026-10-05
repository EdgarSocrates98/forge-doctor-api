# Changelog

All notable changes to `forge-doctor-api` are recorded here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
entries are grouped by factory spec wave and dated by git history —
this file records what shipped, not what was planned.

The package is `0.1.0` and unreleased. See
[docs/release.md](docs/release.md) for the recorded version decision
and [docs/release-evidence.md](docs/release-evidence.md) for the
verification matrix.

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
