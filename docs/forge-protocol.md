# Forge Protocol

Typed, versioned contracts for cross-product exchange:

```
forge-doctor-api  = deterministic + offline + evidence-first (producer)
api-forge         = agentic engineering (consumer)
the-forger        = orchestration/routing (consumer)
```

`forge_doctor_api.handoff.protocol` — `PROTOCOL_VERSION = 1`.

## Models

| Model | Fields | Role |
|---|---|---|
| `ForgeRequest` | request_id, target, requested_capabilities, clock | consumer → Doctor |
| `ForgeHandoff` | handoff_id, bundle_ref, analysis_rev, refs, capabilities, unknowns | Doctor → consumer |
| `ForgeRef` | ref_id, kind, entity?, sha256?, summary | typed reference |
| `ForgeCapability` | name, status, unknowns | observed capability |
| `ForgeReceipt` | analysis_rev, handoff_id, consumer, result_link | consumer ack → Doctor |
| `ForgeResult` | status, summary, refs | typed result surface |
| `ForgeRoute` | route_id, source, destination, capability | routing record |

## Rules

- **Strict parse** — `*.parse(dict)` rejects unknown fields unless they
  use the `x-*` extension namespace; `ProtocolError` on violations.
- **Version check** — `protocol_version` must equal 1.
- **Deterministic builders** — `build_request`, `build_handoff`,
  `build_receipt`, `build_result`; clocks are injected, never wall time.
- **Unknowns are typed refs** — `ForgeHandoff.unknowns` carries
  `ForgeRef(kind="unknown")`; nothing fabricates a capability.
- **Receipts link back** — `ForgeReceipt.analysis_rev` binds the
  consumer's result to the exact analysis revision it consumed.

## Handoff V2

`assemble_bundle(handoff_version=2, report=report)` adds to the V1
bundle: `handoff_id` (sha256 of the V1 body — deterministic across
machines), `analysis_rev` (report content hash), per-domain
`domain_sha256`, `doctor://` `context_refs`, and `capabilities`.
