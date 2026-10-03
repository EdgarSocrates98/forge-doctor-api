# Migration intelligence

`forge_doctor_api.migrate` classifies **portability** between API
styles. It never generates migration code or target contracts — it
reports what carries over, what changes shape, what is lost, and what is
unknown.

## Classifications

Every dimension verdict rolls up into one class:

| Class | Meaning |
|---|---|
| `DIRECT` | Semantics carry over unchanged. |
| `APPROXIMATE` | Mappable with documented semantic drift. |
| `REDESIGN_REQUIRED` | The target model is structurally different. |
| `NO_EQUIVALENT` | No equivalent exists in the target. |
| `UNKNOWN` | Evidence insufficient to classify. |

Rollup is worst-dimension-wins, and `UNKNOWN` outranks `APPROXIMATE`:
an unassessed dimension must not produce a clean verdict.

## Assessment entry points

- `assess_rest_to_grpc(model, ...)` — per operation: request/response
  mapping, status semantics (HTTP→gRPC code table lives in the
  `grpc-behaviors` pack), streaming, metadata/headers, error model,
  timeouts, idempotency.
- `assess_rest_to_graphql(model, ...)` — defaults to
  `REDESIGN_REQUIRED`; an endpoint is never treated as an automatic
  direct field mapping.
- `assess_sync_to_async(...)` — request-response vs delivery semantics,
  correlation, retry/DLQ, ordering, event schema.
- `assess_gateway_to_gateway(...)` — route/policy portability between
  gateway capability packs.
- `assess_contract_version` / `assess_version_upgrade` — OpenAPI
  version moves (e.g. `nullable` → `type: […, "null"]` is APPROXIMATE,
  not DIRECT).
- `client_generation_impact(diff)` — which SDK surface members a diff
  breaks.

## Decision briefs (§167)

`DecisionBrief` answers questions like *"can we retire v1?"* or *"REST →
gRPC feasible?"* with `facts`, `constraints`, `capabilities`,
`tradeoffs`, and `unknowns` — deliberately **no verdict field**. The
Doctor surfaces evidence; the decision belongs to the human/agent caller.
