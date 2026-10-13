# Gaps — passo-1 mission

Differences between documented intent and verified state, mapped to the
mission prompt sections. Each gap lists the evidence and the spec that
closes it (or an explicit defer decision). Spec numbering continues at
035 in `factory/specs/inbox/`.

## G1 — Trust / CI (prompt §6–§10)

| Gap | Evidence | Resolution |
|---|---|---|
| No independent quality CI (pytest × 3.11–3.13, ruff, mypy, build, wheel smoke, CLI smoke, lab, offline proof, determinism replay) | only `.github/workflows/doctor-scan.yml` (self-scan gate) | spec 035 |
| No deterministic integration gate test (same input → byte-identical export across JSON/JSONL/agent/graph/handoff) | no replay test in `tests/` | spec 036 |
| `contract inspect` is a public stub returning "not implemented" | `cli/__init__.py` `_not_implemented` | implement properly — spec 035 |
| No SECURITY.md, Dependabot, CODEOWNERS, contribution/release policy | `ls` confirmed absent | spec 035 (hygiene slice) |

## G2 — Unified engine (§11–§16)

| Gap | Evidence | Resolution |
|---|---|---|
| `scan_project` never calls routes, gateway, iac, cache, twin, drift, fanout, capability analyzers | `scan.py` source | specs 037–040 |
| Every analyzer re-walks `iter_files()` independently; no artifact discovery/classification stage, no evidence inventory | `scan.py`, `mcp.py` | spec 037 (Artifact Discovery + EvidenceStore) |
| No `AnalysisPlan` — all pipelines run regardless of evidence | `scan.py` | spec 038 |
| No canonical `DoctorReport` — `ScanReport` carries findings+diff only | `scan.py` | spec 039 |
| `contract inspect`, `graph`, `security inspect` each re-implement their own mini-pipeline | `cli/` | folded into unified pipeline — spec 040 |

## G3 — Runtime scalability (§17–§23)

| Gap | Evidence | Resolution |
|---|---|---|
| `load_runtime_project` accumulates `all_spans`, `all_summaries` — streaming input ≠ streaming processing | `runtime/loader.py` L187-205 | spec 041 |
| `keep_spans=True` forced in scan, `DoctorApi`, lab runner | `scan.py` L181, `handoff/mcp.py` L100, `lab/runner.py` L137 | specs 040–042 |
| No bounded trace assembler / online aggregators (latency, error, fanout, retry, payload, downstream, SLO) | loader is monolithic | spec 042 |
| No benchmark gate: suite covers functional cases only; recorded benchmark is manual, no regression thresholds, no env record | `tests/test_performance.py`, `factory/runs/scale-benchmark.json` | spec 043 |

## G4 — Forge-native integration (§24–§29)

| Gap | Evidence | Resolution |
|---|---|---|
| No Forge Protocol contracts (request/capability/context-ref/receipt/result/route) — serializable, versioned | `handoff/model.py` has bundle only | spec 046 |
| Handoff bundle is V1: no evidence refs, no content hashes, no graph slices | `handoff/bundle.py` | spec 047 |
| No receipts → no traceability/caching/audit chain Doctor→Forge→Doctor | absent | spec 046 |
| No content hashing of artifacts/evidence/operations/findings | absent | spec 046 |

## G5 — Context broker (§30–§34)

| Gap | Evidence | Resolution |
|---|---|---|
| No `doctor://` context references | absent | spec 048 |
| No context slices (service/operation/finding/security/runtime/change/blast/migration) | absent | spec 048 |
| No token-economy metrics (bytes reduced, evidence retained, unknowns preserved) | absent | spec 048 |
| No delta context (new/resolved findings, changed evidence/graph/unknowns between reports) | absent | spec 049 |

## G6 — MCP (§35–§40)

| Gap | Evidence | Resolution |
|---|---|---|
| No real MCP server — `DoctorApi` is a local callable, no transport, no JSON-RPC lifecycle | `handoff/mcp.py` docstring | spec 045 (stdlib JSON-RPC over stdio; no new runtime deps) |
| No `forge-doctor-api mcp` command, no tools/resources schema surface | absent | spec 045 |
| No protocol/determinism/offline tests for MCP | absent | spec 045 |

## G7 — Public SDK (§41–§44)

| Gap | Evidence | Resolution |
|---|---|---|
| `sdk.py` is a stub | 3-line file | spec 044 |
| No public/experimental/internal boundary declared | — | spec 044 |
| No schema versioning policy across SDK/output/handoff/MCP/knowledge/plugin | partial (`SCHEMA_VERSION` in export only) | specs 044–048 |

## G8 — Framework intelligence (§45–§49)

| Gap | Evidence | Resolution |
|---|---|---|
| Only `FastApiAdapter` exists; adapter contract is the minimal `scan()` Protocol — no auth/schemas/deps/middleware/error-handler surfaces | `analyzers/routes/` | specs 050–052 |
| No Spring Boot adapter (Java static analysis) | absent | spec 051 |
| No Express/NestJS adapter (TS static analysis) | absent | spec 052 |
| Adversarial fixtures exist only for FastAPI-era cases | `labs/adversarial/` | per-adapter fixtures in specs 051–052 |

## G9 — Plugin platform (§50–§55)

| Gap | Evidence | Resolution |
|---|---|---|
| No plugin manifest format (id/version/doctor_api range/provides/trust/capabilities) | `plugins/` has descriptors only | spec 053 |
| No registry duties: discovery, compatibility, capability index, conflict detection, activation | `PluginRegistry` is a tuple wrapper | spec 053 |
| No conformance harness (determinism, offline, evidence compliance, unknown semantics, no side effects) | absent | spec 054 |
| No `forge-doctor-api plugins` CLI | absent | spec 053 |

## G10 — Forge Lab 2.0 (§56–§60)

| Gap | Evidence | Resolution |
|---|---|---|
| Corpus is 25 authored scenarios; no pinned-revision real-world fixtures | `labs/` | spec 058 (progressive 50→100→500 via sanitized fixtures) |
| No per-rule sample-size / coverage-confidence metrics — a 1-expected-1-hit rule reads as "proven" | `lab/report.py` | spec 058 |
| Adversarial classes missing: vendored/broken-syntax/partial-config/duplicate-service/similar-name/mixed-language/monorepo | `labs/adversarial/` | spec 058 |

## G11 — Infrastructure depth (§61–§66)

| Gap | Evidence | Resolution |
|---|---|---|
| K8s model lacks HPA, ServiceAccount, NetworkPolicy, ConfigMap/Secret-reference semantics | `iac/model.py` | spec 055 |
| Terraform: resource shells only — no reference extraction, no API GW/LB/IAM/Lambda/ECS/EKS semantics | `iac/parser.py` | spec 055 |
| CloudFormation explicitly deferred | `iac/` | spec 055 |
| SAM/CDK-synth/Serverless/Helm/Kustomize unplanned | absent | roadmap (explicit defer) |

## G12 — Gateway depth (§67–§68)

| Gap | Evidence | Resolution |
|---|---|---|
| Four dialects only; capability extraction (auth, rate-limit, timeout, retry, CB, transforms, CORS, mTLS, size limits, cache, canary) partial | `gateway/` | spec 056 — extend *after* unified pipeline |
| No separation platform-capability vs project-config | model is flat | spec 056 |

## G13 — Graph 2.0 (§69–§72)

| Gap | Evidence | Resolution |
|---|---|---|
| Graph built per-command (`graph` CLI merges contract+routes+clients only); runtime/gateway/infra/cache/policy/owner edges never enter one graph | `cli` `graph` cmd | spec 057 |
| No graph slices (operation/service/finding/change-centered) | absent | spec 057 |
| Edge-evidence discipline is enforced by `Relationship` model — kept | `core/models.py` | invariant |

## G14 — Temporal intelligence (§73–§76)

| Gap | Evidence | Resolution |
|---|---|---|
| No `DoctorSnapshot` (revision, content hash, schema version, knowledge versions) | absent | spec 059 |
| No snapshot delta (added/removed APIs, contract changes, new/resolved findings & unknowns, regressions) | absent | spec 059 |
| No architectural-regression detection (fanout growth, gateway drift, retry multiplication, surface growth, auth weakening) | absent | spec 059 |

## G15 — Migration 2.0 (§77–§79)

| Gap | Evidence | Resolution |
|---|---|---|
| `migrate/` classifies portability but has no migration graph (current→required capability, blockers, redesign) | `migrate/model.py` | spec 060 |
| REST→gRPC semantics (status codes, streaming, idempotency, error model) not evaluated | `migrate/engine.py` | spec 060 |

## G16 — Security depth (§80–§81)

| Gap | Evidence | Resolution |
|---|---|---|
| BOLA/BFLA candidate classes not modelled; confidence tiers (confirmed / candidate / missing-evidence / unknown) not separated per finding family | `security/`, `checks/apisec/` | spec 061 |

## G17 — Reliability depth (§82–§83)

| Gap | Evidence | Resolution |
|---|---|---|
| Retry amplification is path-explicit only (`reliability path`); no configured/observed/theoretical tiers in findings | `reliability/` | spec 062 |

## G18 — Cache 2.0 (§84–§85)

| Gap | Evidence | Resolution |
|---|---|---|
| No read-op↔cache↔writer-op invalidation graph; TTL/key/vary/SWR/SIE only where declared | `cache/` | spec 063 |

## G19 — Knowledge lifecycle (§86–§88)

| Gap | Evidence | Resolution |
|---|---|---|
| Packs have versions but no provenance/released_at/verified_at/compatibility lifecycle, no pack validation suite, no explicit update path | `knowledge/` | spec 064 |

## G20 — Doctor performance (§89–§90)

| Gap | Evidence | Resolution |
|---|---|---|
| No engine-level benchmark (cold/warm scan, files processed/skipped, analyzers enabled) | absent | spec 065 |
| No incremental-analysis groundwork via content hashes | absent | specs 046+065 |

## G21 — Doctor observability (§91)

| Gap | Evidence | Resolution |
|---|---|---|
| No analysis stats (files discovered/analyzed/ignored, per-stage elapsed, counts) — kept deterministic (stats side-channel, never in exports) | absent | spec 066 |

## G22 — Output contract (§92–§94)

| Gap | Evidence | Resolution |
|---|---|---|
| SARIF: no partial-fingerprint/stable-id fields, no rule metadata beyond id/name; agent format has no token benchmark | `output/writers.py` | spec 067 |

## G23 — Docs as contract (§95–§96)

| Gap | Evidence | Resolution |
|---|---|---|
| No doc↔code consistency check (documented commands/modules/schema exist) | absent | spec 068 |
| No ADRs for offline-first, no-LLM, unknown semantics, plugin trust, MCP boundary, streaming runtime, Forge Protocol, context refs | `docs/` lacks `adr/` | spec 068 |

## G24 — Release engineering (§97)

| Gap | Evidence | Resolution |
|---|---|---|
| `0.1.0` → no 0.x milestone mapping, no release policy doc | `pyproject.toml`, absent `release policy` | spec 069 + `docs/roadmap.md` |

## G25 — Supply chain (§98–§99)

| Gap | Evidence | Resolution |
|---|---|---|
| No lockfile strategy, SBOM, dependency-rationale doc, dependency audit | absent | spec 069 (stdlib-only tooling; no new runtime deps) |

## G26 — Cross-doctor (§100–§101)

| Gap | Evidence | Resolution |
|---|---|---|
| No external data-reference contract for Forge Doctor Data | absent | spec 070 — contracts only, zero coupling |

## Deliberately not built (confirmed, stays out)

- Live cluster/cloud/gateway-admin access — offline-first is the product.
- Composite health score — fabricated simplification.
- Name-similarity edges — "probably connected" is permanently out.
- LLM calls, arbitrary code execution of analyzed projects.
