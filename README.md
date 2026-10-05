<p align="center">
  <img src="docs/assets/logo.png" alt="Forge Doctor API" width="440">
</p>

# Forge Doctor API

Deterministic, offline-first, evidence-first engine for API architecture
intelligence.

Forge Doctor ("the Doctor") inspects API projects — contracts, source
code, configuration, and exported runtime artifacts — and produces
structured, evidence-bearing findings. It never calls a model, never
fetches a URL, and never guesses: anything it cannot establish from
local evidence is surfaced as an explicit `UnknownFact`.

Status: `0.2.0` — the full deterministic surface is implemented (scan,
diff, diagnose, inventory, lab, handoff). This is **not** a stable public
API commitment; interfaces may still change before 1.0.

## Design principles

| Principle | What it means in practice |
|---|---|
| Deterministic | Same inputs → byte-identical findings, ordering, and exports. No LLM calls anywhere. |
| Offline-first | Zero network access. Host interaction happens only through `ProjectContext`. Tests hard-block sockets. |
| Evidence-first | Every finding carries `Evidence` (file + line + summary) and a `Confidence` (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`). |
| Low false positives | Passive/absence-of-evidence cases are emitted as *candidates*, never as verdicts. |
| Explicit unknowns | Missing files, unresolvable references, dynamic code → `UnknownFact` records, not silence. |
| Portable | Pure Python, no platform-specific imports; supports Python 3.11/3.12/3.13 on Linux/Windows/macOS. |

The Doctor is the **deterministic** half of the Forge product family:
it observes and classifies. Agentic code generation lives in `api-forge`
(a separate project); this repository has no dependency on it.

## Installation

```bash
pip install .            # runtime deps: typer, rich, pyyaml
pip install .[graphql]   # optional: graphql-core for GraphQL parsing
```

Requirements: Python >= 3.11. For development:

```bash
pip install pytest ruff mypy types-PyYAML build
python -m pytest -q
python -m ruff check .
python -m mypy src
```

## Quickstart

```bash
# Full deterministic scan of a project directory
forge-doctor-api scan ./my-service

# Scan + CI gate: fail on new breaking changes vs a baseline contract
forge-doctor-api scan ./my-service --fail-on breaking --baseline ./last-release

# Emit SARIF for GitHub code scanning, or a compact agent-readable format
forge-doctor-api scan . --format sarif --out results.sarif
forge-doctor-api scan . --format agent
```

Exit codes: `0` scan ran and gate passed · `1` gate failed ·
`2` usage/misconfiguration error.

## Command tour

```text
forge-doctor-api scan TARGET        all pipelines + optional §178 gate
forge-doctor-api inventory TARGET   fleet answers over a workspace or repo
forge-doctor-api diff OLD NEW       semantic contract diff + typed events
forge-doctor-api diff OLD NEW --pr  + PR-intel summary and blast radius
forge-doctor-api fingerprint FILE   semantic fingerprint of a contract
forge-doctor-api graph TARGET       merged contract/route/client graph
forge-doctor-api blast-radius O N   operation → clients → services impact
forge-doctor-api diagnose TARGET    root-cause episodes from evidence
forge-doctor-api explain DIR TOKEN  evidence chain for one finding
forge-doctor-api lab [labs]         Forge Lab corpus: precision/recall
forge-doctor-api contract diff O N  contract-level diff
forge-doctor-api contract compat …  compatibility classification
forge-doctor-api runtime requests   per-request execution table
forge-doctor-api runtime baseline   performance baselines per endpoint
forge-doctor-api runtime regress…   regressions vs baseline
forge-doctor-api security inspect   passive security evidence + findings
forge-doctor-api reliability inspect  timeouts/retries/idempotency/SLOs
forge-doctor-api reliability path     hop-by-hop effective policy
```

`--help` on any command lists its options. See
[docs/cli.md](docs/cli.md) for the full reference.

## What it understands

- **Contracts**: OpenAPI 3.x (YAML/JSON), AsyncAPI, GraphQL SDL +
  introspection, gRPC `.proto`.
- **Source**: FastAPI route discovery, client call-site extraction
  (Python/JS/TS), GraphQL client queries (`gql` tagged literals).
- **Config**: timeouts, retries, rate limits, idempotency headers,
  authentication/CORS/mTLS/TLS evidence, gateway routes, ownership
  files, policy files.
- **Runtime**: OTLP/OTEL JSON traces, access-log records — ingested as
  compact per-request summaries (raw spans are not retained).

From those inputs it produces: OAS/ASYNC/GQL/GRPC contract checks,
contract-drift and semantic compatibility diffs, client impact and blast
radius, versioning/deprecation analysis, observability + performance
regression findings, reliability checks (retry amplification, SLO
budgets), passive OWASP API Top-10 candidates, policy violations, an API
digital twin, root-cause diagnosis, safe-fix classification, multi-repo
workspace analysis, fleet intelligence, migration portability
assessments, and compact handoff bundles for agentic tools.

## Documentation

- [docs/architecture.md](docs/architecture.md) — pipeline layout, models, determinism contract
- [docs/cli.md](docs/cli.md) — every command, option, and exit code
- [docs/output-formats.md](docs/output-formats.md) — console/JSON/JSONL/SARIF/agent + CI gate
- [docs/checks.md](docs/checks.md) — finding model, namespaces, confidence semantics
- [docs/compatibility.md](docs/compatibility.md) — cross-protocol diff taxonomy, decision tables, client-impact coverage
- [docs/runtime-evidence.md](docs/runtime-evidence.md) — trace/log ingestion, history, perf & SLOs
- [docs/runtime-scale.md](docs/runtime-scale.md) — streaming bounds, memory curve, perf budget gate, snapshot formats
- [docs/policies.md](docs/policies.md) — policy files, inheritance, exceptions, ownership
- [docs/workspace-fleet.md](docs/workspace-fleet.md) — multi-repo manifests + inventory
- [docs/knowledge-packs.md](docs/knowledge-packs.md) — versioned knowledge data + plugin SDK
- [docs/migration.md](docs/migration.md) — portability assessments + decision briefs
- [docs/handoff.md](docs/handoff.md) — `ApiHandoffBundle`, `DoctorApi`, Forger routing
- [docs/infrastructure.md](docs/infrastructure.md) — gateway/mesh declared config + Kubernetes/IaC evidence
- [docs/cache.md](docs/cache.md) — declared cache policies, layers, invalidation risk
- [docs/lab.md](docs/lab.md) — Forge Lab corpus, ground truth, precision/recall
- [docs/output-contract.md](docs/output-contract.md) — v1 export schemas (json/jsonl/sarif/agent/report) + evolution rules
- [docs/forger-boundary.md](docs/forger-boundary.md) — Doctor ↔ API Forge ↔ The Forger typed boundary
- [docs/release-policy.md](docs/release-policy.md) — versioning, public surfaces, release checklist, SBOM
- [docs/release-v0.1.md](docs/release-v0.1.md) — quality gate, packaging, hermetic proofs
- [docs/roadmap.md](docs/roadmap.md) — shipped coverage vs planned waves
- [docs/adr/](docs/adr/) — architecture decision records
- [docs/development.md](docs/development.md) — repo layout, test/lint/typecheck, adding a check

## Repository layout

```text
src/forge_doctor_api/   engine (analyzers, checks, models, CLI)
tests/                  pytest suite (offline-blocked sockets)
labs/                   Forge Lab corpus: golden + adversarial fixtures
factory/                Loop Factory specs, run records, quality gate
.github/workflows/      doctor-scan.yml CI gate
docs/                   documentation
```
