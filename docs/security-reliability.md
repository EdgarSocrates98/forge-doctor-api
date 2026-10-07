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
operations by declared identity — never by name similarity. A
`security:` requirement naming an *undeclared* scheme resolves to no
enforcement claim — the declaration is ambiguous (`APISEC011`), never a
fabricated `APISEC013` break.

**Authorization coverage (APISEC001, APISEC002).** An op is treated as
covered when any of these hold:

- contract evidence — `x-roles`/`x-scopes`/`x-claims`/security
  requirement scopes bound to the operation;
- gateway evidence — a policy whose declared `prefix`/`path`/name
  scope equals or prefix-contains the normalized operation path
  (`*` covers all);
- implementation evidence — middleware or `dependencies=[...]` names
  carrying explicit authorization intent (`role`, `permission`,
  `authoriz*`, `rbac`, `guard`, `acl`, `owner`, `scope`), recorded on
  `AuthorizationPolicy.via` so the mechanism name stays visible and no
  role is fabricated.

Authentication-only middleware (`*AuthMiddleware`, `Security(...)`
deps) is authN evidence — it lands on `route.auth`/`impl_schemes`, not
in `authz_ops`. `APISEC001`/`APISEC002` findings still carry the
object-level unknown when fired.

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
- Retry counts inside documentation or sample content are never
  policies: the config walkers skip `example`/`examples`/`description`/
  `comment`/`notes`/`properties`/`schema`/`items`/`components`/`value`/
  `content`/`requestBody`/`responses`/`parameters`/`headers`/`default`/
  `enum` subtrees (OpenAPI example blocks, schema properties, prose).

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
  A shared key *string* is not a shared key space: the join is
  suppressed — with a `CacheGraph.unknowns` record — when declared
  `vary` sets diverge between policies, when a declared `vary` axis is
  authz-bearing (`Authorization`/`Cookie`/`Proxy-Authorization`,
  i.e. per-principal partitioning), or when declared `scope`
  (`private`/`public`/…) diverges.
- Config policies also record `vary` (list or comma string),
  `scope`/`private`/`public`, and `stale_if_error`/`staleIfError`/
  `stale-if-error` (folded into `stale_policy` as
  `stale-if-error:<value>`).

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

## Incident intelligence (§60-§62, §165)

`diagnose()` episodes carry `symptom`, `candidates`, `observed`
signals, `affected_services` (downstream impact), evidence refs, and
`unknowns`. A `CandidateCause` is never emitted with an empty evidence
path and no explanation — candidates lacking evidence carry an explicit
`UnknownFact` (`missing: evidence path for this candidate cause`).
Tiers are `DERIVED` (change + runtime agree on a hop), `RUNTIME`
(observed signal, no matching change), `STATIC` (change only), and
`UNKNOWN` — worded as candidates, never verdicts.

## SLO budgets (§46-§47)

`error_budget()` consumes only evidenced request-status signals — it
computes `error_rate`/`availability`-style objectives (`error`,
`availab*`, `success`, `failure` metrics) from counted windowed
executions. Any other metric (latency percentiles, freshness,
throughput) has no declared signal to consume → `sufficient=False`
with an `UnknownFact`; no interpolation, no fabricated number. Fewer
than `MIN_SAMPLES` (8) requests in the objective window likewise yields
`sufficient=False` + unknowns.

## Adversarial coverage matrix (spec 088)

| Adversarial case | Expected | Guard |
| --- | --- | --- |
| `{id}` path param + global authz middleware | no APISEC001; impl `via` policy exists | `impl_authz` records authz-intent middleware; engine joins `via` policies |
| `/admin/*` op + gateway role prefix | no APISEC002; policy entity exists | `prefix`/`path` scope keys + path-prefix join |
| `*` in comment/description only | no APISEC004; real CORS policy still loads | YAML parser drops comments; `wildcard` reads parsed origins only |
| `retries: N` in `examples:`/`properties:` | no RetryPolicy for the subtree | `_NON_EVIDENCE_KEYS` descent skip |
| `security: [{ghost: []}]` undeclared scheme | APISEC011 ambiguous; NO APISEC013 | unresolvable declarations → `req=None` (unknown), never a break |
| retry product over a missing layer | `complete=False`, `potential_attempts=None`, missing hops named | `amplification()` per-hop policy binding |
| caller budget < callee budget | `IMPOSSIBLE`/`AT_RISK` verdict | `evaluate_timeout_budget` parallel/sequential bounds |
| PUT/DELETE verb only | RELAPI008 fires; no IDEMPOTENT record | `aggregate_idempotency` never infers from verbs |
| shared `key` + divergent `vary`/authz axis/scope | no APICACHE003; `CacheGraph.unknowns` records the partition | declared-vary/scope guards |
| runtime-only candidate cause without span evidence | candidate carries `UnknownFact` | diagnose evidence-path guarantee |
| latency/freshness SLO or < 8 samples | `sufficient=False` + unknowns | metric gate + `MIN_SAMPLES` |

## Honest boundaries

| Surface | Can claim | Cannot claim |
| --- | --- | --- |
| auth chain | declared scheme ↔ enforcement plane join | that enforcement is *correct* — runtime auth behavior is out of scope |
| retry amplification | exact product when every hop declares `max_attempts` | partial products — missing hops stay `UNKNOWN` |
| timeout budget | IMPOSSIBLE/AT_RISK/FEASIBLE on declared budgets | feasibility when a downstream timeout is undeclared |
| idempotency | verdict from asserting sources only | verb-based inference; binding by name similarity |
| cache | conflicts on identical declared key+variant space | conflicts when `vary`/scope partition the space |
| diagnose | ranked candidates with evidence-or-unknown | verdicts; causes without a traceable path |
| SLO | consumed budget from request counts | budgets for non-error metrics or thin windows |

## Limits

- Only declared identifiers join planes and scopes. A gateway route to
  an upstream that shares a service's name but is not the declared
  target produces an `UnknownFact` path, not a link.
- Enforcement evidence today covers the framework route adapters and
  gateway policy artifacts; runtime auth behavior is out of scope for
  static analysis.
- `x-idempotent` with a non-boolean value records an asserted-but-
  unparseable contract source → `UNKNOWN`, not a guess.
