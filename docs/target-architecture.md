# Target architecture — passo-1

The shape the passo-1 specs build toward, consistent with the CORE /
ADAPTERS / INTEGRATION separation (prompt §110). This documents
direction; every item lands through a spec, not by decree.

## Unified pipeline (prompt §15)

```text
ProjectContext (hermetic: files + clock, the only I/O boundary)
      ↓
Artifact Discovery        core/discovery.py
      single walk → classify: source|contract|runtime|iac|gateway|mesh|
      policy|config|client|workspace|ownership|documentation
      ↓
Evidence Inventory        core/evidence_store.py
      dedup refs, content hashes, origin map — immutable, in-memory
      ↓
AnalysisPlan              core/plan.py
      artifact classes present → analyzer set to run (lazy, no waste)
      ↓
┌─────────────────────────────────────────────────────────────┐
│ Analyzers (adapters):                                        │
│  contracts (openapi/asyncapi/graphql/grpc) · routes ·        │
│  clients · gateway · mesh · iac · cache · runtime · security │
│  reliability · policies · version · workspace                 │
└─────────────────────────────────────────────────────────────┘
      ↓
Normalized Models  →  ServiceGraph (evidence-backed edges only)
      ↓                      ↓
Digital Twin         Correlation (runtime↔declared)
      ↓
Check engines (OAS COMPAT DRIFT CLIENT APISEC RELAPI APIPERF OBSAPI
               GQL GRPC ASYNC POLICY GATEWAY IAC CACHE …)
      ↓
Findings + Capabilities + Unknowns + Impact
      ↓
DoctorReport          core/report.py — canonical, compact refs
      ↓
Output / SDK / MCP / Handoff / ContextBroker
```

## Runtime engine 2.0 (prompt §19–§23)

```text
artifact → decoder → TraceAssembler (bounded windows,
        completion heuristics w/ explicit unknowns)
      → RequestExecution (streamed)
      → online aggregators: latency | error | fanout | retry |
        payload | downstream | slo  (incremental stats; any
        quantile approximation is labelled, never exact)
      → summary; raw spans discarded unless an operation requires
        bounded retention
```

`keep_spans` defaults to false everywhere; retention is opt-in and
bounded.

## Integration surface

```text
forge_doctor_api.sdk      Doctor façade — the ONLY public boundary
forge_doctor_api.mcp      JSON-RPC stdio server (stdlib; tools +
                         resources over DoctorApi/DoctorReport)
forge_doctor_api.handoff  Bundle V2: refs + hashes + slices + receipts
forge_doctor_api.context  doctor:// refs, slices, delta, token metrics
forge_doctor_api.forge    Forge Protocol contracts (serializable,
                         versioned; no circular deps)
```

## Invariants carried forward (non-negotiable)

- Deterministic, offline-first, evidence-first; unknowns first-class.
- No raw payloads/spans/secrets in stored or exported data.
- Edges and findings require evidence; name-similarity is never truth.
- All emitted collections sorted; no implicit clock.
- Runtime deps stay at typer/rich/pyyaml (+graphql extra). MCP and any
  future transports are stdlib or optional extras.
