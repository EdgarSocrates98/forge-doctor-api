You are implementing Loop Factory spec `034-cache-model`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\034-cache-model.md`
        Spec hash: `737cbce25c6baf19a4a4648730ff8f379214b883a348fa47d021d073aa17d8c5`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
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
