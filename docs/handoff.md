# Handoff and integration surface (§133–138)

The Doctor is the deterministic observer; `handoff/` packages its
outputs for agentic consumers (Forge tools) without ever handing them
raw payloads.

## `ApiHandoffBundle`

A compact, serializable summary of one project:

- operation identities + contract **references** (not schema bodies)
- findings, breaking changes, affected clients
- runtime regressions, security candidates, reliability signals
- spec-022 safe-fix candidates
- explicit `unknowns` and `knowledge_versions`

Bundles are deterministic — same repo, same bytes — and contain no raw
contract payloads. `ExternalReference`s point at other systems (tickets,
dashboards) by identity, never by inlined content.

## `DoctorApi`

A typed local method surface (`handoff/mcp.py`) — the shape an MCP-style
transport can expose unchanged, with no server machinery required:

```text
get_service()            titles/versions/op counts
get_api()                method+path surface
get_operation(id)        one operation's identity/location
get_contract()           doc identities + versions (never bodies)
get_clients()            call-site model summary
get_runtime()            observability/execution summary
get_security()           passive security model
get_reliability()        timeouts/retries/SLOs
get_breaking_changes()   requires a `before` context
get_blast_radius()       diff → clients → services
impact_report()          combined change report
```

All methods are serializable and deterministic; diff-based methods are
enabled by constructing `DoctorApi(ctx, before=before_ctx)`.

## Forger routing (§136/§215)

`route_request(...)` classifies a task and emits an evidence-bearing
routing record:

| Request shape | Route |
|---|---|
| `domain=api` | `doctor-api` (analysis) → `api-forge` (implementation) |
| data references | `data-doctor`; implementation tasks may also route to `spark-forge` |
| unknown domains | `unrouted` + `UnknownFact` |

Routing is advisory evidence — the Doctor does not dispatch work.
