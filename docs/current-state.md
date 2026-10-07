# Current state — passo-1 baseline

Evidence-based snapshot of `main` after spec 034
(`22995fe`). Every claim is backed by a file; nothing here is
aspirational. For the gap list see `gaps.md`, for the target shape see
`target-architecture.md`.

## What exists

| Area | Module | State |
|---|---|---|
| Core models | `core/models.py` | Frozen dataclasses, deterministic `to_dict`/`to_json`, `Finding`/`UnknownFact`/`Evidence`, entity ids `kind:domain:identifier`, redaction on construction |
| Hermetic context | `core/context.py` | `ProjectContext` — all file I/O + injected clock; `resolve()` refuses escapes |
| OpenAPI | `analyzers/openapi/` | 3.x YAML/JSON loader, refs, identity, shape, graph, knowledge |
| AsyncAPI / GraphQL / gRPC | `analyzers/{asyncapi,graphql,grpc}` | Parsers, models, graphs, per-protocol checks |
| Routes | `analyzers/routes/` | `FrameworkAdapter` Protocol + `FastApiAdapter` (AST, no target-code execution) + `scan_graph` |
| Clients | `analyzers/clients/` | Python (`requests`/`httpx`) + JS (`fetch`/`axios`) call-site extraction |
| Runtime | `analyzers/runtime/` | OTLP JSON + access-log adapters, **streaming input**, `build_traces`, `executions_from_traces`, `RequestHistory` |
| Gateway / mesh | `analyzers/gateway/` | Kong/Envoy/AWS-APIGW/NGINX dialect parsers, `GatewayModel`, `ServiceMeshModel` |
| IaC | `analyzers/iac/` | K8s manifests, Terraform/Helm/CFN resource extraction, `infra_graph` |
| Cache | `analyzers/cache/` | Declared `CachePolicy`, layers, `InvalidationRisk` candidates |
| Checks | `checks/` | 12 engines: OAS, COMPAT, DRIFT, CLIENT, APISEC, RELAPI, APIPERF, OBSAPI, GQL, GRPC, ASYNC, POLICY |
| Change intel | `change/` | `ChangeEvent` taxonomy, PR intel, blast radius, baseline store |
| Digital twin | `twin/` | `ApiDigitalTwin` declared/observed/configured + `TwinDrift` |
| Diagnose | `diagnose/` | `ApiIncidentEpisode` root-cause episodes |
| Policies | `policy/` | Declarative policies, exceptions, ownership precedence |
| Workspace / fleet | `workspace/`, `fleet/` | Multi-repo manifests, cross-repo edges, `inventory` CLI |
| Migration | `migrate/` | Portability classification (REST→gRPC/GraphQL, sync→async) |
| Safe fix | `safefix/` | SAFE / REVIEW_REQUIRED / MANUAL_ONLY classification |
| Performance | `perf/` | Baselines, budgets, critical path, experiments, FanoutSignal |
| Knowledge packs | `knowledge/` | Versioned YAML packs, capability detection, `knowledge_versions()` |
| Plugins | `plugins/` | Adapter `Protocol`s (Framework/Gateway/Contract/Runtime/SecurityRulePack) + `TrustClass` load boundary |
| Handoff | `handoff/` | `ApiHandoffBundle` (references+summaries), `DoctorApi` local method surface, routing |
| Output | `output/writers.py` | JSON / JSONL / SARIF 2.1.0 (location-anchored only) / agent compact — all with schema+tool+knowledge versions |
| Scan gate | `scan.py` | `scan_project` + `evaluate_gate` (breaking/security/policy; UNKNOWN never blocks) |
| CLI | `cli/` | `scan`, `inventory`, `lab`, `contract diff|compatibility|inspect`, `diff`, `fingerprint`, `graph`, `blast-radius`, `runtime requests|baseline|regressions`, `security inspect`, `reliability inspect|path`, `diagnose`, `explain` |
| Lab | `lab/` + `labs/` | 25-scenario corpus (golden/adversarial), precision/recall per family, run records |
| CI | `.github/workflows/doctor-scan.yml` | Self-scan gate on PR + dispatch (spec 030) |
| Quality record | `factory/` | 34 archived specs, run records, `quality-gate-v0.1.json`, `scale-benchmark.json` |

## DOCUMENTED vs IMPLEMENTED vs TESTED vs INTEGRATED

| Surface | Documented | Implemented | Tested | Integrated into `scan` |
|---|---|---|---|---|
| Contracts (OAS/Async/GQL/gRPC) | yes | yes | yes | yes |
| Security + reliability models | yes | yes | yes | yes |
| Runtime ingestion | yes | yes | yes | yes — but `keep_spans=True` |
| Clients | yes | yes | yes | unknowns only |
| Policies/ownership | yes | yes | yes | yes (when policy files exist) |
| Routes (FastAPI) | yes | yes | yes | **no** — only `graph`/`security inspect` commands |
| Drift (contract-vs-impl) | yes | yes | yes | **no** — not called by `scan` |
| Gateway / mesh | yes | yes | yes | **no** |
| IaC / Kubernetes | yes | yes | yes | **no** |
| Cache | yes | yes | yes | **no** |
| Digital twin | yes | yes | yes | **no** |
| Fanout signal | yes | yes | yes | **no** |
| Version model | yes | yes | yes | partial (policy context only) |
| Capabilities | yes | yes | yes | **no** |
| `DoctorApi` (MCP surface) | yes | yes | yes | local-only, no transport |
| `sdk.py` public SDK | no | **empty stub** | no | **no** |
| `contract inspect` | in help | **stub → exit 3** | yes (exit code) | placeholder |

## Verified hard rules (still true)

- Determinism: models reject sets, sort keys; `ProjectContext` holds the
  only clock; offline test suite hard-blocks sockets.
- No network/process imports anywhere in `src/` (AST-enforced in
  `tests/test_package.py`).
- Runtime deps: `typer`, `rich`, `pyyaml` only (+ `graphql` extra).
- `keep_spans=False` default exists in loaders — but callers override it.

## What is not real yet (summary; detail in `gaps.md`)

1. No independent quality CI (pytest/ruff/mypy/build matrix, wheel
   smoke, determinism replay, offline proof in CI).
2. `scan` is not the unified pipeline — six+ analyzers never run there.
3. Runtime processing is not streaming: `all_spans`/`all_summaries`
   accumulate in `load_runtime_project`; scan/MCP/lab force
   `keep_spans=True`.
4. No public SDK (`sdk.py` is a 3-line stub).
5. No MCP transport — `DoctorApi` is a local callable only.
6. No Forge Protocol contracts (receipts, content hashes, delta).
7. No context broker (`doctor://` refs, slices, token accounting).
8. No framework adapters beyond FastAPI; no plugin manifest,
   registry activation, or conformance harness.
9. No incremental analysis, snapshots/deltas, analysis stats,
   docs-as-contract checks, ADRs, supply-chain artifacts.
