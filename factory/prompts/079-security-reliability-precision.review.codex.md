Review Loop Factory spec `079-security-reliability-precision` against current working tree.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\079-security-reliability-precision.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions from stabilization prompt Phase I +
  §9-§11, §14-§18.
- Problem: security/reliability checks exist (test_security,
  test_reliability, test_cache, test_gateway_mesh, test_iac) but
  evidence chains are shallow — "auth present" without chain proof,
  "retry configured" without amplification math, cache claims inferred
  from header names alone.
- Out of scope: dynamic tracing, traffic observation, or importing
  gateway/mesh SDKs (static declared-config evidence only).
- Review failure: amplification claimed without multiplying declared
  retry budgets; auth "chains" that collapse to boolean presence;
  cache findings derived from header-name heuristics (explicitly
  banned by the prompt).
- Riskiest assumption: retry topology can be joined across config
  layers deterministically — RESOLVED: topology joins only on
  declared identifiers (service names, route ids) per §15 infra-graph
  rule; ambiguous joins produce UnknownFact, not a guessed edge.
- Smallest acceptable: auth-chain evidence (declared scheme → applied
  scope → enforcement point), retry topology with amplification =
  product of declared budgets on joined hops, timeout-budget
  comparison (downstream budget vs upstream caller), idempotency-key
  evidence on mutation operations, cache evidence restricted to
  declared TTL/key/invalidation/stale-policy fields.

# Context

Phase I + hardening sections 9-11, 14-18. Existing surfaces to
deepen: `analyzers/` security + reliability + cache + gateway/mesh
scanners, `graph/` for retry topology edges, `client_impact` for
timeout budget propagation. The prompt explicitly bans inferring
cache behavior from header names alone — only declared config.

# Acceptance Criteria

- `analyzers/security/`: auth chain evidence record
  `{scheme_declared, enforcement_point, scope, evidence_refs}`;
  chain breaks produce findings, not just absences.
- `analyzers/reliability/`: retry topology edges on declared
  identifiers; amplification finding = product of hop budgets with
  per-hop evidence; timeout-budget mismatch finding when caller
  budget < callee declared latency/retry budget.
- Idempotency: mutation operations lacking declared idempotency-key /
  Idempotency-Key / x-idempotency produce evidence-backed findings;
  presence produces capability evidence.
- Cache: findings built only from declared TTL/key/invalidation/
  stale-policy fields; header-name-only inference removed or
  downgraded to UNKNOWN; writer-reader conflict detection on shared
  declared keys.
- Gateway/mesh: AWS API Gateway + Kong + Envoy + NGINX + Traefik
  declared-config scanners where fixtures exist; Istio/Linkerd/Envoy
  retries/timeouts/circuit-breakers/mTLS/traffic-split evidence.
- Lab scenarios for each new check incl. negative (absent → UNKNOWN)
  and adversarial (comment/string fake-outs) cases.
- `docs/security-reliability.md` coverage matrix updated.
- pytest/ruff/mypy pass.

# Constraints

- Every claim carries evidence_refs to declared config lines.
- Joins on declared identifiers only; ambiguity → UnknownFact.
- No behavior inferred from naming conventions alone (§17 cache rule,
  generalized).
