# Contract compatibility

Version-to-version contract diffs classify every detected change into a
shared taxonomy (`CompatibilityClass`) carried by `ContractChange`
records — never a bare verdict. Each change records `kind`,
`classification`, `side` (REQUEST / RESPONSE / META), `subject`, `path`,
`detail`, `before`/`after`, and its `SourceLocation`.

## Taxonomy

| Class | Meaning | Gate posture |
|---|---|---|
| `BREAKING` | Structural proof the old client surface no longer works. | Blocks compatibility verdicts. |
| `POTENTIALLY_BREAKING` | Semantics may shift without structural proof (widened responses, added union members, binding changes). | Reported, never blocking alone. |
| `NON_BREAKING` | Provably safe evolution (additive, loosened auth). | Recorded for traceability. |
| `UNKNOWN` | Evidence too partial to decompose safely. | Emitted **with** `UnknownFact`s; never upgraded to BREAKING. |

Unknown-first policy: when input evidence is missing or ambiguous
(unresolvable `$ref`, malformed document, opaque payload), the change
classifies `UNKNOWN` and the finding carries the unknowns that would
resolve it. Classification is evidence-bound — there is no
"probably-breaking" promotion.

## Per-protocol decision table

### OpenAPI (`contract diff`, `diff_models`)

| Change | Class | Kind |
|---|---|---|
| Endpoint / method removed | BREAKING | `endpoint_removed`, `method_removed` |
| Required parameter added / param removed | BREAKING | `param_added_required`, `param_removed` |
| Optional parameter added | POTENTIALLY | `param_added_optional` |
| Parameter type changed | BREAKING / POTENTIALLY | `type_changed_request` |
| Request field became required | BREAKING | `request_field_required` |
| Response field removed | BREAKING | `response_field_removed` |
| Response field added | POTENTIALLY | `response_field_added` |
| `nullable` removed (either side) | BREAKING | `type_changed_*` |
| `nullable` added (response) | POTENTIALLY | `response_type_widened` |
| `nullable` added (request) | — | widened input, not emitted |
| `discriminator` added/removed/`propertyName` change | BREAKING | `type_changed_*` |
| `discriminator.mapping` change | POTENTIALLY | `type_changed_*` |
| Enum value removed / added | BREAKING / POTENTIALLY | `enum_removed` / `enum_added` |
| `additionalProperties` tightened | BREAKING | `type_changed_*` |
| Response status / content-type removed | BREAKING | `status_removed`, `content_type_removed` |
| Auth tightened / loosened | BREAKING / NON_BREAKING | `auth_tightened` / `auth_loosened` |
| oneOf/anyOf/allOf branch-count change | UNKNOWN | `unresolvable` |
| Unresolvable schema change | UNKNOWN | `unresolvable` (+ `UnknownFact`s) |

### GraphQL (`graphql_breaking_changes`, `diff_graphql_schemas`)

| Change | Class | Check id |
|---|---|---|
| Field removed (object / interface / input) | BREAKING | GQL002 |
| Required argument added | BREAKING | GQL003 |
| Field/arg nullable→non-null | BREAKING | GQL004 |
| Enum value removed | BREAKING | GQL005 |
| Union member removed | BREAKING | GQL011 |
| Directive set changed (type or field) | POTENTIALLY | GQL012 |
| Union member added | POTENTIALLY | GQL013 |

Direction polarity: output positions break readers; input positions
(input objects, arguments) break writers — `side` records which.

### gRPC (`grpc_breaking_changes`, `diff_proto_models`)

| Change | Class | Check id / kind |
|---|---|---|
| Field removed without `reserved` | BREAKING | GRPC003 |
| Field removed with `reserved` | POTENTIALLY | GRPC003 |
| Field number reused (different name) | BREAKING | GRPC004 |
| Field type changed, same wire group | POTENTIALLY | `GRPC_TYPE_CHANGED` |
| Field type changed, different wire group | BREAKING | `GRPC_TYPE_CHANGED` |
| Streaming mode flipped | BREAKING | GRPC006 |
| Enum value renumbered | BREAKING | GRPC008 |
| Oneof membership changed / member added | BREAKING / POTENTIALLY | GRPC009 |
| Package/service removed or renamed | BREAKING | `GRPC_RENAME` (change kind) |
| Method removed | BREAKING | `GRPC_METHOD_REMOVED` (change kind) |

Kinds without a dedicated check id still appear in
`ContractDiff.changes`; only catalog-mapped kinds emit findings.

### AsyncAPI (`asyncapi_breaking_changes`, `diff_asyncapi_models`)

| Change | Class | Check id |
|---|---|---|
| Channel removed / added | BREAKING / POTENTIALLY | ASYNC009 / ASYNC010 |
| Operation removed | BREAKING | ASYNC011 |
| Operation action flipped (send↔receive) | BREAKING | ASYNC012 |
| `correlationId` location changed | BREAKING | ASYNC013 |
| Message removed | BREAKING | ASYNC014 |
| Message payload schema changed | BREAKING (POTENTIALLY when drift is partial) | ASYNC015 |
| Message content-type changed | POTENTIALLY | ASYNC016 |
| Binding set changed (channel/op/message) | POTENTIALLY | ASYNC017 |

Payload resolution follows one local `$ref`/`payload_ref` hop into
component schemas, then runs the unified schema diff — property-level
drift inside a stable ref still surfaces.

## Client-impact coverage

`analyzers/clients/` extracts call sites evidence-gated — nothing is
emitted without a static anchor:

| Surface | Languages | Detection anchor |
|---|---|---|
| `requests` / `httpx` | Python | module imports, `Client()`/`Session()` bindings, `verb(url)` calls |
| `fetch` / `axios` | JS/TS | `fetch(url)`, `axios.method(url)`, `axios({url})` |
| Feign | Java | `@FeignClient` type or `import feign.RequestLine`; `@RequestLine`, `@GetMapping`/`@PostMapping`…, `@RequestMapping(method=…)`; class-level `@RequestMapping` prefixes |
| Generated OpenAPI client | Python | `openapi_client` / `*_api` module imports + `*Api(...)` constructor bindings → `operation` = method name |
| gRPC stub | Python | `*_pb2_grpc` / `*_grpc` imports + `*Stub(channel)` bindings → `operation` = RPC name |
| GraphQL document | `.graphql`/`.gql` | executable `query`/`mutation`/`subscription` operations → `operation` + `response_fields` |
| `gql`/`graphql` templates | JS/TS | tagged template literals parsed as documents |

Non-HTTP call sites (generated clients, gRPC stubs, GraphQL ops) carry
`operation` instead of `method`/`path`. Computed paths and ambiguous
constructs land in `unknowns`, never guessed.

## Deprecation readiness

`DeprecationReadiness` (fleet report, `deprecations`) is emitted per
deprecated contract with `remaining_clients`, `remaining_client_subjects`,
`replacement`, `contract_age_days`, and `observed_traffic`. Signals that
are absent — no client repos scanned, no runtime evidence — surface as
`None` **plus** recorded `UnknownFact`s ("no client repos" ≠
"zero clients"), never as invented zeros.
