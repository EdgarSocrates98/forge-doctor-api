# Security & reliability precision

Evidence discipline for the `security`, `reliability`, `cache`, and
`gateway` surfaces. Every finding names the declared configuration or
source location it was built from; an absent or ambiguous join produces
an `UnknownFact` — never a guessed link, never silence.

## Authentication chain (APISEC011, APISEC013)

Each contract operation resolves three evidence planes — **contract**
(`security` requirements), **implementation** (`Security(...)` /
framework auth idioms on the matched route), **gateway** (declared
policies binding the operation path). The join produces an
`AuthChainLink` record per operation:

```text
{scheme_declared, enforcement_point, scope, evidence_refs}
```

- `scheme_declared` — comma-joined requirement names resolved for the
  op (op-level requirements first, then global).
- `enforcement_point` — `implementation` | `gateway` |
  `contract-only` | `none`.
- `chain_complete` — `true` when a declared scheme lands on an
  enforcement plane; `false` is a **chain break**; `null` means
  evidence was insufficient.

| Check | Fires when |
| --- | --- |
| `APISEC011` | op-level `security:` resolves no requirement, or no security evidence exists at any level → `UNKNOWN` |
| `APISEC013` | contract declares a scheme but no enforcement plane answers (declared-but-unenforced), or enforcement exists without a contract declaration (enforced-but-undeclared) |

Ambiguous joins stay `UNKNOWN`; schemes are joined by declared name,
operations by declared identity — never by name similarity.

## Retry topology & amplification (RELAPI001, RELAPI002, APIREL001)

`retry_policy:`/`retryPolicy:`/`retries:` dicts and `num_retries`,
`numRetries`, `maxAttempts`, `max_attempts`, `retries`, `attempts`
scalars become `RetryPolicy` records. Istio `retries: {attempts,
perTryTimeout, retryOn}` and Kong `retries: N` + `*_timeout` keys are
covered.

- `amplification()` multiplies only explicitly declared `max_attempts`
  along the hop set; a hop with no declared policy lands in `missing`
  and the product stays unknown.
- `run_depth_checks` consumes *evidenced* edges only: CALLS graph
  relationships, resolved gateway route targets, and declared lab
  `hops`. Gateway/mesh retry+timeout entries fold into edge-scoped
  policies (`<dialect>-><subject>`), so `APIREL001` reports the real
  product with per-hop file evidence (e.g. `3x (kong.yaml) x 3x
  (app.yaml) -> 9 attempts`).
- `RELAPI002` flags every retried scope whose idempotency verdict is
  not `IDEMPOTENT`; a scope declared in multiple files reports once.

## Timeout budgets (RELAPI003, RELAPI004, APIREL002)

`timeout`, `per_try_timeout`/`perTryTimeout`, `connect_timeout`,
`upstream_rq_timeout`, `request_timeout`, `deadline` become
`TimeoutConfig` records.

- `RELAPI003` evaluates declared hop chains via
  `evaluate_timeout_budget`: `IMPOSSIBLE` when the parallel bound
  exceeds the caller budget, `AT_RISK` when only the sequential bound
  does; missing declarations produce `UnknownFact`, not defaults.
- `APIREL002` fires on an evidenced edge when the caller budget is
  shorter than the callee's declared timeout, or the callee has none.
  An edge-scoped timeout (`caller->callee`) counts as caller-budget
  evidence for that edge.
- `RELAPI004` names scopes with timeouts but no call-site deadline
  propagation evidence.

## Idempotency (RELAPI002, RELAPI008)

Verdicts come only from declared sources (`aggregate_idempotency`):

- `key_header`/`idempotency_key`/`idempotencyKey`/`x_idempotency_key`
  in config → `idempotency_key` source (supports).
- `idempotent`/`declared`/`x_idempotent` booleans →
  `contract_metadata` source.
- `unique_constraint`/`db_uniqueness` → `db_uniqueness` source.
- OpenAPI `x-idempotent` / `x-idempotency` / `x-idempotency-key` on an
  operation → sources bound to the operation's declared identity
  (`operationId`, else `method_path:` identity).

`RELAPI008` fires per mutating operation (POST/PUT/PATCH/DELETE) with
no bound `IDEMPOTENT` evidence. Binding uses declared identifiers only
— `operationId`, the path template, `METHOD path`, or the full
identity; a subject that merely *resembles* the operation does not
bind. HTTP verbs alone never decide: PUT/DELETE are not exempt, GET is
never flagged. A bound but non-idempotent verdict names the bound
subject.

## Cache precision (APICACHE001-003)

Policies exist only where declared: `cache:`/`caching:`/`cdn:`/`ttl:`
config keys, or a declared `Cache-Control` response header.

- A `Cache-Control` **header name is presence evidence only** — the
  header value is contract-invisible, so ttl/key/invalidation/
  stale_policy stay `None` and the policy carries an explicit
  `UnknownFact`. No field is ever derived from the header name.
- `APICACHE001` — declared `ttl` plus a schema-evidenced writer edge →
  stale-window candidate.
- `APICACHE002` — same subject with conflicting `stale_policy` values
  across declared layers.
- `APICACHE003` — two policies share a declared `key` whose subjects
  split across an evidenced writer operation and an evidenced read
  operation (joined by `operationId`/path/`METHOD path`/identity).

## Gateway & mesh dialects

Declared-config scanners cover AWS API Gateway, Kong, Envoy, NGINX, and
Traefik gateways plus Istio, Linkerd, and Envoy mesh markers —
routes, upstreams, retries, timeouts, circuit breakers, mTLS, traffic
splits, and edges where declared (`docs/infrastructure.md` has the
marker tables). With `run: [gateway]` the lab pipeline loads these
models; their declared retry/timeout entries join reliability evidence
via `dialect->subject` scopes, and route targets become evidenced
edges for `APIREL001`/`APIREL002`.

## Labs

| Scenario | Exercises |
| --- | --- |
| `security/auth-chain-break` | contract-declared apiKey, unenforced route → APISEC013 |
| `security/cache-shared-key` | shared declared `key` across writer+reader → APICACHE003; header-only unknowns |
| `reliability/idempotency-gap` | POST without evidence → RELAPI008; `x-idempotency-key` op → silent |
| `reliability/gateway-edge-join` | Kong retries+timeout → `kong->svc` edge policies → APIREL001 |
| `adversarial/config-comments` | comments/string literals resembling config → no policies, no findings |

## Limits

- Only declared identifiers join planes and scopes. A gateway route to
  an upstream that shares a service's name but is not the declared
  target produces an `UnknownFact` path, not a link.
- Enforcement evidence today covers the framework route adapters and
  gateway policy artifacts; runtime auth behavior is out of scope for
  static analysis.
- `x-idempotent` with a non-boolean value records an asserted-but-
  unparseable contract source → `UNKNOWN`, not a guess.
