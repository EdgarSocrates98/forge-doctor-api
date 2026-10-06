# Architecture

Forge Doctor API is a deterministic analysis engine. It reads local
project evidence, normalizes it into typed models, runs catalogued check
suites, and emits findings with evidence. There is no planner, no LLM,
no network call — the same tree of files always produces the same bytes
of output.

## Package map

```text
src/forge_doctor_api/
├── core/            Model base, Finding/Evidence/UnknownFact, entity ids,
│                    ProjectContext (all host I/O), redaction, export,
│                    discovery (one classified walk), evidence_store
│                    (content-addressed artifacts), plan (AnalysisPlan),
│                    graph (ServiceGraph + slices/EdgeExport), stats
│                    (spec-066 counters), cache (spec-065 incremental)
├── analyzers/       Input normalization, one subpackage per source kind
│   ├── openapi/     OpenAPI 3.x YAML/JSON -> OpenApiProjectModel
│   ├── asyncapi/    AsyncAPI documents -> AsyncApiProjectModel
│   ├── graphql/     SDL/introspection + client queries -> GraphQLProjectModel
│   ├── grpc/        .proto files -> GrpcProjectModel
│   ├── routes/      framework adapters (FastAPI/Flask AST, Spring,
│   │                Express, NestJS text scanners) -> RouteScan
│   ├── clients/     client call-site extraction -> ApiClientModel
│   ├── gateway/     §71-73 declared gateway/mesh config (Kong, Envoy,
│   │                AWS API Gateway, NGINX, Traefik) + mesh edges
│   │                (Istio, Linkerd) -> GatewayModel, ServiceMeshModel
│   ├── iac/         §74-76 K8s manifests + bounded HCL + CFN -> InfraModel
│   ├── cache/       §151-153 declared cache policies + cache graph ->
│   │                ApiCacheModel
│   ├── runtime/     OTLP traces + access logs -> bounded streaming
│   │                assembler (ADR-0002) -> TraceModel, executions,
│   │                RequestHistory, ApiObservabilityModel
│   └── version/     API versioning model (URI/header/media strategies)
├── checks/          Catalogued check suites, one namespace per family
│   ├── oas/         OAS001-020 contract checks
│   ├── compat/      semantic diff -> ContractChange + CompatibilityClass
│   ├── drift/       contract-vs-impl DRIFT### + §147 error contracts
│   ├── client/      CLIENT### impact findings
│   ├── apisec/      APISEC001-012 passive security candidates (incl.
│   │                unknown-auth semantics)
│   ├── relapi/      RELAPI### reliability checks (+retry/timeout depth)
│   ├── perf/        APIPERF### runtime regression checks
│   ├── observability/  OBSAPI### ingestion/coverage checks
│   ├── graphql/ grpc/ asyncapi/  per-protocol GQL/GRPC/ASYNC checks
├── change/          ChangeEvent taxonomy, PR intel, blast radius, baseline store
├── diagnose/        ApiIncidentEpisode — root-cause episodes
├── policy/          declarative policies, exceptions, ownership precedence
├── twin/            ApiDigitalTwin — declared/observed/configured views + drift
├── workspace/       multi-repo manifests, cross-repo edges, chains
├── fleet/           fleet questions, portfolio, complexity, readiness,
│                    ForgeHandoff ingestion (spec 070)
├── migrate/         portability classification + migration graph
│                    (spec 060)
├── temporal.py      snapshot store + architectural regressions (spec 059)
├── handoff/         ApiHandoffBundle (V1/V2), Forge Protocol types,
│                    context broker (doctor:// refs), delta contexts,
│                    MCP server (optional extra, ADR-0003), boundary
│                    (spec 070 typed The-Forger/API Forge surface)
├── knowledge/       versioned YAML packs + capability detection +
│                    pack lifecycle manifests (spec 064)
├── plugins/         adapter Protocols + TrustClass boundaries +
│                    manifest validation + offline conformance
├── safefix/         spec-022 fix classification (SAFE/REVIEW/MANUAL)
├── perf/            baselines, budgets, critical path, experiments,
│                    capacity/cost signals, FanoutSignal (§59)
├── lab/             Forge Lab runner + precision/recall + realworld
│                    corpus metrics (spec 058)
├── output/          §175 writers: JSON, JSONL, SARIF 2.1.0, agent compact
│                    (v1 contract frozen — docs/output-contract.md)
├── report.py        DoctorReport — one canonical compact report (spec 039)
├── scan.py          §177-§178 unified scan + gate evaluation + stats +
│                    opt-in incremental
├── sdk.py           Doctor facade — programmatic entry points
└── cli/             typer commands (thin wrappers over the packages above)
```

## Data flow

```text
files on disk
     │  (all access via ProjectContext: iter_files/read_text/resolve;
     │   .forge-doctor/ tool state is never project content)
     ▼
discover → EvidenceStore → AnalysisPlan   one classified walk, one
     │                                    content-addressed inventory,
     │                                    evidence-driven plan
     ▼
analyzers/*  ──► typed models (OpenApiProjectModel, ApiSecurityModel, …)
     │           every model is a frozen dataclass; unknowns are data,
     │           not exceptions. Under --incremental, heavy loader
     │           results are reused from .forge-doctor/cache keyed by
     │           artifact sha + analyzer + tool version + config
     ▼
checks/*     ──► Finding tuples (id, severity, confidence, evidence,
     │           entity_ids, source_location, remediation, unknowns)
     │           checks always recompute — never replayed from cache
     ▼
higher layers ──► diff events, twin drift, episodes, blast radius,
                  fleet answers, migration assessments, handoff bundles
     ▼
output/* / cli ──► console tables, JSON/JSONL/SARIF/agent exports,
                   DoctorReport (stats: deterministic counters always,
                   timing only under --stats-timing)
```

## Decisions of record

Accepted architecture decisions live in `docs/adr/`:

- [ADR-0001](adr/ADR-0001-unified-pipeline.md) — unified deterministic
  pipeline over per-domain CLIs
- [ADR-0002](adr/ADR-0002-bounded-runtime.md) — `keep_spans=False`
  default and bounded runtime retention
- [ADR-0003](adr/ADR-0003-mcp-optional-extra.md) — MCP as an optional
  extra
- [ADR-0004](adr/ADR-0004-untrusted-plugins.md) — untrusted plugins are
  never imported
- [ADR-0005](adr/ADR-0005-compact-refs.md) — compact refs over payloads
  in handoff/context

ADRs are immutable once accepted; a changed decision gets a new ADR
that supersedes the old one.

## The determinism contract

- All collections are sorted before emission (findings by
  `(id, entity_ids, description)`; files iterated in sorted order).
- No wall-clock reads inside the engine — anything that needs "today"
  receives it via `ProjectContext.now()` from an injected clock, so a
  scan is reproducible with a fixed clock.
- `Model` is a frozen `@dataclass` with `to_dict()`; serialization is
  the persistence boundary. Nothing mutates models in place.
- Set iteration never leaks into output ordering.

## Evidence and confidence

`Finding` requires `evidence` — a tuple of `Evidence(kind, source,
line?, summary)`. `EvidenceKind` distinguishes `STATIC` (contract/
source), `CONFIG` (config files), `OBSERVED_METADATA` (exported
artifacts/inventories), `RUNTIME` (observed traffic), and `DERIVED`
(computed from other evidence — never stronger than its inputs).

`Confidence` is semantic: `HIGH` multiple strong signals or direct
evidence; `MEDIUM` single strong signal; `LOW`/`CANDIDATE`-grade static
absence-of-evidence; `UNKNOWN` when inputs are missing — and UNKNOWN
findings must also list their `unknowns`. Gates never let an UNKNOWN
finding block a build.

## Unknowns are first-class

`UnknownFact(subject, missing, resolution)` appears everywhere:
unresolvable `$ref`s, dynamic client URLs, missing runtime evidence,
workspace members that are absent. Callers get an explicit record of
what the engine could not establish and why — the exact opposite of a
guess.

## Redaction

`core/redaction.py` masks secrets in every serialized surface:
authorization/cookie headers, tokens/passwords/api keys, bearer/basic
credentials, JWTs, URL userinfo passwords, and provider token formats
(`sk-live-*`, `AKIA*`, `ghp_*`, `xox*`). Redaction is always on; there is
no flag to disable it.

## Offline guarantee

Nothing in `src/` imports `socket`, `urllib`, `http`, `requests`,
`httpx`, or `subprocess` (enforced by `tests/test_package.py`). Offline
tests additionally monkeypatch `socket.socket`/`create_connection` to
raise, proving the scan path stays hermetic
(`tests/test_offline.py`). External documents referenced by contracts
(`$ref` to a URL) are recorded as `UnresolvedExternalRef` — never
fetched.

## Extensibility boundary

`plugins/` defines adapter `Protocol`s (`FrameworkAdapter`,
`RuntimeAdapter`, `CheckSuite`) and a `TrustClass` taxonomy. Untrusted
plugin code is described/inspected but never imported or executed —
`describe_untrusted` parses plugin manifests statically. Built-in
adapters register under `TrustClass.BUILTIN`.
