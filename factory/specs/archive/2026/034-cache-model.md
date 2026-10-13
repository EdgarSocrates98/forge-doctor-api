---
id: 034-cache-model
title: CachePolicy model, layer taxonomy, invalidation-risk candidates
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §151, §152, §153 and
  the existing `cache_status`/`APIPERF008` runtime fields.
- Problem: `RequestExecution.cache_status` and `APIPERF008` cover the
  *runtime* side, but §151–153 ask for the *declared* side — a
  `CachePolicy` model (location/ttl/key/invalidation/stale_policy), a
  layer taxonomy, and evidence-based invalidation-risk candidates.
- Out of scope: measuring real cache hit ratios (runtime evidence
  already handles that); cache correctness proofs.
- Review failure: a CachePolicy fabricated from defaults, or an
  invalidation-risk finding without evidence of both caching *and*
  mutation paths.
- Riskiest assumption: where cache policy evidence lives — RESOLVED:
  OpenAPI `Cache-Control` response headers + config keys (`cache:`,
  `cdn:`, `ttl:` blocks); absent evidence → absent policy.
- Smallest acceptable: models + config/header extraction + one
  invalidation-risk candidate + tests.

# Context

§151 `CachePolicy{location, ttl, key, invalidation, stale_policy}`.
§152 layers: `client, CDN, gateway, service, database`. §153:
invalidation risk — *only evidence-based*: e.g. an endpoint that both
declares caching and mutates shared state is a candidate; absence of
evidence → nothing emitted.

# Acceptance Criteria

- `CacheLayer` enum: `client|cdn|gateway|service|database|unknown`.
- `CachePolicy` per §151, every field optional-but-evidenced: a field
  is `None` unless the source declared it.
- Extraction: OpenAPI response `Cache-Control` headers → `client`/`cdn`
  hints; config keys under `cache:`/`cdn:`/`ttl:` → `service`/`gateway`
  policies; both carry SourceLocation evidence.
- `InvalidationRisk` candidate: emitted only when a policy exists AND
  the same entity has mutation evidence (write methods on the path);
  `Confidence.LOW`, `finding_class` candidate — never a verdict.
- `ApiCacheModel` aggregates policies + risks + unknowns.
- Determinism, offline, no new dependencies; tests for each layer,
  the risk positive+negative, malformed config; pytest/ruff/mypy pass.

# Constraints

- Declared-or-unknown: never synthesize a TTL or layer the source
  didn't state.
- Candidate-grade output only — consistent with §119 resource signals.
