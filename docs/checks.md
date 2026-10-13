# Findings and check catalog

Every finding is a `Finding` model:

| Field | Meaning |
|---|---|
| `id` | `{NAMESPACE}{3-4 digits}` — e.g. `OAS010`, `APISEC003`. |
| `title` | Short human title from the catalog spec. |
| `description` | Instance detail — names the exact element. |
| `severity` | `CRITICAL`/`HIGH`/`MEDIUM`/`LOW`/`INFO` — impact if the finding is real. |
| `confidence` | `HIGH`/`MEDIUM`/`LOW`/`UNKNOWN` — how sure the evidence is. |
| `evidence` | One or more `Evidence` records: kind (`STATIC`/`CONFIG`/`RUNTIME`/`DERIVED`/`HYPOTHETICAL`), source path, optional line, summary. |
| `entity_ids` | Canonical `kind:domain:identifier` entity references. |
| `source_location` | Project-relative path + line when the finding is anchored to a file. |
| `remediation` | Short fix hint when the catalog defines one. |
| `unknowns` | `UnknownFact`s — required when confidence is `UNKNOWN`. |

"Candidate" checks describe risk *potential* — absence of evidence, not
proof of a defect. They carry `Confidence.LOW` and `finding_class`
`CANDIDATE`/`CONFIGURATION_RISK`, and never block gates.

## OpenAPI — OAS001–020

Contract validity and hygiene over `OpenApiProjectModel`:

- `OAS001` invalid spec version · `OAS002` unresolved local `$ref` ·
  `OAS003` duplicate `operationId` · `OAS004` missing `operationId` ·
  `OAS005` undocumented response · `OAS006` default-only response ·
  `OAS007` inconsistent error schema · `OAS008` request body without
  schema · `OAS009` response without schema
- `OAS010` public API without security requirement (candidate) ·
  `OAS011` per-operation security override · `OAS012`/`OAS013` path
  parameter mismatches · `OAS014` schema without type · `OAS015`
  deprecated without sunset metadata · `OAS016` server-URL environment
  mismatch (candidate) · `OAS017` unrestricted `additionalProperties`
  (candidate) · `OAS018` unused component schema · `OAS019` circular
  `$ref` depth risk · `OAS020` no tags/domain grouping (candidate)

## Contract compatibility — COMPAT### (`diff`)

Semantic diff classes, classified `BREAKING`/`POTENTIALLY_BREAKING`/
`NON_BREAKING` with a `ChangeSide` (REQUEST vs RESPONSE polarity):

- `COMPAT001` endpoint removed · `COMPAT002` method removed ·
  `COMPAT003` required parameter added · `COMPAT004` parameter removed ·
  `COMPAT005` param/field type changed · `COMPAT006` field became
  required · `COMPAT007` response field removed · `COMPAT008` response
  type narrowed · `COMPAT009` enum value removed · `COMPAT010` status
  code removed · `COMPAT011` auth tightened · `COMPAT012` content-type
  removed · `COMPAT020`–`COMPAT028` additive/loosening candidates ·
  `COMPAT030` unresolvable change detail

## Drift — DRIFT001–010

Contract vs implementation (framework route scan):

- `DRIFT001` documented op not implemented · `DRIFT002` implemented
  route absent from contract · `DRIFT003` method mismatch ·
  `DRIFT004`/`DRIFT005`/`DRIFT006` param/request/response schema
  mismatch · `DRIFT007` status-code drift · `DRIFT008` auth drift ·
  `DRIFT009` deprecated contract still implemented · `DRIFT010`
  undocumented breaking implementation.

`checks/drift/error_contract.py` additionally evaluates an org
standard error contract (§147) — e.g. the bundled `RFC7807` preset
(`application/problem+json` + `type`/`title`/`status`) — producing
per-operation `CONFORMS`/`VIOLATION`/`UNKNOWN` verdicts.

## AsyncAPI — ASYNC001–008

`ASYNC001` channel without message schema · `ASYNC002` missing
correlation id · `ASYNC003` producer/consumer schema drift · `ASYNC004`
retry without DLQ evidence · `ASYNC005` unordered processing assumption
· `ASYNC006` incompatible message evolution · `ASYNC007` missing
consumer ownership · `ASYNC008` operation without delivery semantics.

## GraphQL — GQL001–010

`GQL001` deprecated field with active clients · `GQL002` field removed ·
`GQL003` required argument added · `GQL004` nullable→non-null · `GQL005`
enum value removed · `GQL006` resolver without authz evidence
(candidate) · `GQL007` unbounded list (candidate) · `GQL008` deep
traversal candidate · `GQL009` N+1 candidate · `GQL010` introspection
exposure policy mismatch.

Input/output polarity follows §123: output positions break readers,
input positions break writers.

## gRPC — GRPC001–007

`GRPC001` call without deadline evidence · `GRPC002` retry on
non-idempotent method · `GRPC003` removed proto field not reserved ·
`GRPC004` field-number reuse · `GRPC005` health service absent ·
`GRPC006` incompatible streaming-mode change · `GRPC007` retry-policy
amplification.

## Client impact — CLIENT001–003

From the client call-site scan + contract diff: `CLIENT001` confirmed
impact · `CLIENT002` in blast radius · `CLIENT003` unresolvable call
site (explicit UnknownFact).

## Passive security — APISEC001–013

OWASP-API-Top-10-shaped candidates over config + contract evidence:
`APISEC001` object-id route without authz evidence · `APISEC002` admin
op without authz · `APISEC003` unauthenticated sensitive op ·
`APISEC004` wildcard CORS · `APISEC005` missing rate-limit evidence ·
`APISEC006` unrestricted expensive op · `APISEC007` unsafe outbound-URL
param (SSRF candidate) · `APISEC008` sensitive property in response ·
`APISEC009` deprecated still reachable · `APISEC010` unsafe third-party
dependency · `APISEC011` unresolvable auth-coverage chain (unknown) ·
`APISEC012` sensitive-named field without protection evidence ·
`APISEC013` auth chain break across contract/impl/gateway planes.

Passive candidates default to `Confidence.LOW` — the `security` gate
category only fires on `HIGH` confidence, so candidates alone never
fail a build.

## Reliability — RELAPI001–008, APIREL001–002

`RELAPI001` retry amplification · `RELAPI002` retried op without
idempotency evidence · `RELAPI003` impossible timeout budget (downstream
timeout ≥ upstream) · `RELAPI004` deadline propagation gap ·
`RELAPI005` no circuit-breaker evidence · `RELAPI006` no health-check
evidence · `RELAPI007` no graceful-shutdown evidence · `RELAPI008`
mutating operation without declared idempotency evidence.
`APIREL001` chained retry amplification on an evidenced edge (computed
bound, per-hop files) · `APIREL002` timeout cascade on an evidenced
edge.

## Performance — APIPERF001–008

Runtime regressions over `RequestHistory`/executions: `APIPERF001` p95
latency regression · `APIPERF002` error-rate regression · `APIPERF003`
downstream latency · `APIPERF004` retry amplification · `APIPERF005`
timeout increase · `APIPERF006` payload growth · `APIPERF007` fan-out
increase · `APIPERF008` cache-effectiveness regression.

## Observability — OBSAPI001–005

`OBSAPI001` missing correlation evidence · `OBSAPI002` trace-propagation
gap · `OBSAPI003` inconsistent operation naming · `OBSAPI004` error
without structured context · `OBSAPI005` missing latency metrics on a
critical operation.

## Policy — POLICY001–010

Org-declared rules (see [policies.md](policies.md)): `POLICY001`
require auth · `POLICY002` require SLO · `POLICY003` no wildcard CORS ·
`POLICY004` min deprecation days · `POLICY005` require operationId ·
`POLICY006` require owner · `POLICY007` documentation coverage ·
`POLICY008` ignored/invalid exception · `POLICY009` widened inherited
policy · `POLICY010` policy file issue.
