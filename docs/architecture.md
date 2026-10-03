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
│                    ProjectContext (all host I/O), redaction, export
├── analyzers/       Input normalization, one subpackage per source kind
│   ├── openapi/     OpenAPI 3.x YAML/JSON -> OpenApiProjectModel
│   ├── asyncapi/    AsyncAPI documents -> AsyncApiProjectModel
│   ├── graphql/     SDL/introspection + client queries -> GraphQLProjectModel
│   ├── grpc/        .proto files -> GrpcProjectModel
│   ├── routes/      framework adapters (FastAPI) -> RouteScan
│   ├── clients/     client call-site extraction -> ApiClientModel
│   ├── runtime/     OTLP traces + access logs -> TraceModel, executions,
│   │                RequestHistory, ApiObservabilityModel
│   └── version/     API versioning model (URI/header/media strategies)
├── checks/          Catalogued check suites, one namespace per family
│   ├── oas/         OAS001-020 contract checks
│   ├── compat/      semantic diff -> ContractChange + CompatibilityClass
│   ├── drift/       contract-vs-impl DRIFT### + §147 error contracts
│   ├── client/      CLIENT### impact findings
│   ├── apisec/      APISEC001-010 passive security candidates
│   ├── relapi/      RELAPI### reliability checks
│   ├── perf/        APIPERF### runtime regression checks
│   ├── observability/  OBSAPI### ingestion/coverage checks
│   ├── graphql/ grpc/ asyncapi/  per-protocol GQL/GRPC/ASYNC checks
├── change/          ChangeEvent taxonomy, PR intel, blast radius, baseline store
├── diagnose/        ApiIncidentEpisode — root-cause episodes
├── policy/          declarative policies, exceptions, ownership precedence
├── twin/            ApiDigitalTwin — declared/observed/configured views + drift
├── workspace/       multi-repo manifests, cross-repo edges, chains
├── fleet/           fleet questions, portfolio, complexity, readiness
├── migrate/         portability classification (REST→gRPC/GraphQL, sync→async)
├── handoff/         ApiHandoffBundle, DoctorApi surface, routing
├── knowledge/       versioned YAML packs + capability detection
├── plugins/         adapter Protocols + TrustClass boundaries
├── safefix/         spec-022 fix classification (SAFE/REVIEW/MANUAL)
├── lab/             Forge Lab runner + precision/recall reports
├── output/          §175 writers: JSON, JSONL, SARIF 2.1.0, agent compact
├── scan.py          §177-§178 unified scan + gate evaluation
├── sdk.py           programmatic entry points
└── cli/             typer commands (thin wrappers over the packages above)
```

## Data flow

```text
files on disk
     │  (all access via ProjectContext: iter_files/read_text/resolve)
     ▼
analyzers/*  ──► typed models (OpenApiProjectModel, ApiSecurityModel, …)
     │           every model is a frozen dataclass; unknowns are data,
     │           not exceptions
     ▼
checks/*     ──► Finding tuples (id, severity, confidence, evidence,
     │           entity_ids, source_location, remediation, unknowns)
     ▼
higher layers ──► diff events, twin drift, episodes, blast radius,
                  fleet answers, migration assessments, handoff bundles
     ▼
output/* / cli ──► console tables, JSON/JSONL/SARIF/agent exports
```

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
source), `CONFIG` (config files), `RUNTIME` (observed traffic),
`DERIVED` (computed from other evidence), and `HYPOTHETICAL` (what-if
views, never mixed into observed state).

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
