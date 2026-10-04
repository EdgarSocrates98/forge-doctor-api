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

## Graph slices (spec 057)

`core/graph.py` exports `slice_graph(graph, root_id, *, depth=1,
direction="both") -> GraphSlice` — a bounded subgraph (nodes, edges,
boundary ids) plus `export_edges(graph) -> tuple[EdgeExport]` carrying
`from_id`, `to_id`, `kind`, evidence ids, and confidence on every edge.
`doctor://graph/{service}` serves a bounded slice through the context
broker; Handoff V2 bundles embed `graph_edges` so consumers get the
evidence-preserving topology without the full graph. An empty or
disconnected root returns an empty slice — absence is data, not a
fabricated neighborhood.

## The-Forger boundary (spec 070)

`handoff/boundary.py` exposes `DoctorBoundary` — the typed exchange
point between the Doctor and its consumers:

- `handle(ForgeRequest) -> ForgeHandoff` — deterministic scan →
  bundle ref + capability/unknown refs
- `summarize(ForgeHandoff) -> ForgeResult` — status + refs only
- `capabilities(ForgeRequest) -> ForgeResult` — capability-only view

The boundary never routes, schedules, implements, or calls out —
no network, subprocess, or target-code execution (AST-enforced by
`tests/test_boundary.py`). `handoff_to_member_fields` converts a
handoff into the compact fields fleet aggregation accepts
(`collect_handoff`). See [forger-boundary.md](forger-boundary.md).
