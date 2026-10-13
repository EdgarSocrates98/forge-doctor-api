# Roadmap and product vision

Where `forge-doctor-api` is, what is deliberately not built, and how
the remaining prompt sections map to shipped code vs. planned work.
Every status claim below is backed by an archived spec in
`factory/specs/archive/2026/` or a doc page — nothing here is
aspirational text dressed up as fact.

## The distinction that drives everything

```text
forge-doctor-api  = deterministic, offline-first, evidence-first
api-forge         = agentic
```

The Doctor *measures and records*; the Forge *decides and acts*. The
Doctor therefore never emits a composite health score, never asserts a
fact without evidence, and never hides an unknown behind a default.

## Shipped — v0.1 (specs 001–030)

| Prompt area | Spec | What exists |
|---|---|---|
| Core models, evidence, entity ids, redaction | 001–004 | `core/` — frozen dataclasses, `Finding`/`UnknownFact`, `{kind}:{domain}:{identifier}` |
| OpenAPI + REST surface | 005–008 | `analyzers/openapi`, `analyzers/routes`, OAS001–020 |
| Compatibility + change intel | 009–013, 020 | `checks/compat` COMPAT001–030, `change/` |
| AsyncAPI / GraphQL / gRPC | 010–012 | protocol analyzers + ASYNC/GQL/GRPC checks |
| Clients + impact | 009, 013 | `analyzers/clients`, CLIENT001–003 |
| Runtime evidence | 014–016 | `analyzers/runtime`, OTLP/logs, `RequestHistory` |
| Reliability | 017 | `reliability/`, RELAPI001–007, SLOs |
| Passive security | 018 | `security/`, APISEC001–010, candidate classes |
| Digital twin + drift | 019 | `twin/`, DRIFT001–010, §147 error contract |
| Root cause + safe fix | 021–022 | `diagnose/`, `safefix/` |
| Policies + ownership | 023 | `policy/`, POLICY001–010, precedence chain |
| Workspace + fleet | 024–025 | `workspace/`, `fleet/`, `inventory` CLI |
| Forge Lab | 026 | `lab/`, 25-scenario corpus, run records |
| Knowledge packs + capability | 027 | `knowledge/`, versioned packs, plugin SDK trust |
| Migration intelligence | 028 | `migrate/`, DIRECT→UNKNOWN classes |
| Handoff + integration | 029 | `handoff/`, `DoctorApi`, MCP surface, routing |
| Release stabilization | 030 | `output/` writers, `scan` gate, CI, packaging, scale record |

## Shipped — gap closure (specs 031–034)

| Prompt area | Spec | What exists |
|---|---|---|
| §59 Fanout signal | 031 | `perf/fanout.py` — `FanoutSignal` with static `CANDIDATE` + runtime `CONFIRMED` tiers |
| §71–§73, §196 Gateway + mesh | 032 | `analyzers/gateway` — Kong/Envoy/AWS-APIGW/NGINX dialect parsers + `ServiceMeshModel` |
| §74–§76 IaC + Kubernetes | 033 | `analyzers/iac` — K8s manifests, chains, Terraform/Helm/CFN, `DEPLOYED_AS` graph link |
| §151–§153 Cache model | 034 | `analyzers/cache` — `CachePolicy`, layers, `InvalidationRisk` candidates |

## Deliberately not built

- **Live system access.** No cluster API, gateway admin API, cloud API,
  or network call of any kind — offline-first is the product, not a
  limitation to fix.
- **Composite health score.** Dimensions and counts are reported;
  a single number would be a fabricated simplification (§191).
- **Inferred relationships.** Name similarity, convention guessing, and
  "probably connected" edges are permanently out of scope.
- **Raw payload retention.** `keep_spans=False` by default; exports
  carry summaries and references, never request bodies.

## Roadmap anchors — passo-1 (specs 035+)

The passo-1 mission (`prompt_evo_passo1.md`) re-anchors the versions on
the PROVE → CONNECT → SCALE → GENERALIZE → EXPAND sequence
(§104). Baseline evidence: `docs/current-state.md`; gap ledger:
`docs/gaps.md`; target shape: `docs/target-architecture.md`.

- **v0.1 (shipped):** the deterministic core — contracts, evidence,
  checks, twin, policies, fleet, handoff, stabilized release (specs
  001–034).
- **v0.2 — Trusted Unified Doctor:** independent quality CI,
  deterministic integration gate, artifact discovery, `AnalysisPlan`,
  `EvidenceStore`, unified `DoctorReport`, unified `scan` (specs
  035–040).
- **v0.3 — Scalable Doctor:** runtime streaming core, bounded memory,
  online aggregation, benchmark gate, incremental-analysis groundwork
  (specs 041–043, 065).
- **v0.4 — Forge-Native Doctor:** Forge Protocol contracts + receipts +
  content hashing, Handoff V2, Context Broker (`doctor://` refs,
  slices, delta), real MCP server, public SDK (specs 044–049).
- **v0.5 — Multi-Framework Doctor:** consolidated framework-adapter
  contract, Spring Boot + Express/NestJS adapters with adversarial
  fixtures, plugin manifest/registry/conformance/CLI, IaC + gateway
  depth, graph 2.0 with slices (specs 050–057).
- **v0.6+ — Proven Doctor:** real-world Forge Lab corpus with
  coverage-confidence metrics, temporal intelligence
  (snapshots/deltas/architectural regression), migration graph,
  security/reliability/cache depth, knowledge-pack lifecycle, engine
  benchmarks, analysis stats, output-contract polish, docs-as-contract,
  ADRs, release + supply-chain engineering, cross-doctor contracts
  (specs 058–070).

Explicitly still deferred (roadmap, not implementation, per §115/§119):
AWS SAM / CDK-synth / Serverless / Helm-depth / Kustomize parsing,
live-system access of any kind, LLM-assisted features, composite
health scores, name-similarity edges, framework generations two and
three (Flask, DRF, Fastify, Quarkus, Micronaut, Go net/http, Gin, Echo,
Chi) until generation one proves the contract.

The rule for future versions is unchanged: a prompt section becomes
code only through a spec with a Grill Gate, acceptance criteria,
verification, independent review, and archive — the same Loop Factory
lifecycle every shipped spec went through.

## §230–§231 — the result

> Deterministic, offline-first, evidence-first engine for API
> architecture intelligence.

Every shipped spec above is evidence of the same sentence working in
practice: scans are byte-identical on re-run, unknowns are explicit
data, findings carry evidence, and the boundary between *declared* and
*confirmed* is enforced by the model layer itself.
