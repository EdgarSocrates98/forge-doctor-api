You are implementing Loop Factory spec `088-security-reliability-adversarial`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\088-security-reliability-adversarial.md`
        Spec hash: `2c894bb4c261372f107a3e77ae74abac57a1a132fad3db251b85d6887873b3d5`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

        Required verification:
        - `python -m pytest -q`
- `forge-doctor-api lab`
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

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 8 and items §12/§13/§15.
- Problem: precision is the RC claim and the suite needs the
  *negative* side proven: cases that must NOT fire findings
  (authz middleware covering a bare id in a path, gateway role
  checks on admin paths, comments mentioning wildcards, retry
  examples in comments). The auth chain, retry topology, retry
  amplification, timeout-budget coherence, idempotency-by-evidence,
  cache adversarial cases, incident-intelligence output shape, and
  SLO budget each need adversarial coverage.
- Out of scope: vulnerability scanning, exploit payloads,
  remediation; any finding family invented for this spec without
  evidence backing.
- Review failure: negatives that are "obviously safe" (no real
  ambiguity); retry counts that multiply through unknown layers;
  incident output that fabricates causes from symptoms.
- Riskiest assumption: no-finding assertions can rot into vacuity
  — RESOLVED: negatives assert both the absence AND that the
  machinery still emitted entities/unknowns (proof the parse ran).
- Smallest acceptable: negative corpus cases + tests proving no
  overclaim; auth-chain link coverage; topology-aware retry math
  with PARTIAL/UNKNOWN fallback; incoherent timeout-budget finding;
  idempotency evidence table; cache adversarial cases; incident
  report shape test; SLO budget doc/test.

# Context

Phase 8. Existing: `checks/security/` + `checks/reliability/`
catalogs, `AuthChainLink`/`APISEC013` (spec 079), gateway/mesh
parsers, `diagnose/` symptom→cause, `reliability/slo.py`,
`perf/criticalpath.py`. Missing: the adversarial negative layer
and topology-aware amplification honesty.

# Acceptance Criteria

- Negative corpus + tests (`tests/fixtures/` adversarial cases or
  inline fixtures): (a) path `{id}` param + global authz
  middleware evidence → no authz finding; (b) admin path +
  gateway role evidence → no finding; (c) wildcard in comment/
  description only → no finding; (d) retry count in example/
  comment → not counted. Each test also asserts entities/unknowns
  exist (parse ran, not a vacuous pass).
- Auth chain: contract/gateway/middleware/method-level/override/
  anonymous-resolution covered per surface; `APISEC013` fires only
  on a real chain break (evidence gap), never when a layer's
  coverage is merely implicit — implicit coverage emits an unknown.
- Retry topology: amplification = product over layers only when
  every layer's factor is evidenced; any missing layer →
  `amplification: PARTIAL` + unknowns listing which layers are
  unmeasured. Client/gateway/mesh/service/downstream attribution
  recorded per factor.
- Timeout budget: a finding (or diagnostic) fires when
  caller-timeout < callee-timeout+margin across evidenced hops —
  test with incoherent chain asserts the finding; coherent chain
  asserts pass.
- Idempotency: `RELAPI008` never infers from verb alone; evidence
  sources table (contract `x-idempotent*`, explicit header param,
  gateway policy) drives classification — verb-only mutation
  emits unknown, not finding. Tests per evidence source.
- Cache adversarial: shared-key writer/reader conflict already
  `APICACHE003`; add — `Vary`-driven variants, authz-aware keys,
  `stale-if-error` evidence, private/public tension; each with
  negative (safe) cases.
- Incident intelligence (`diagnose/`): output carries
  symptom → candidate causes → evidence path → unknown links →
  downstream impact; test asserts no candidate cause is emitted
  without an evidence path or an explicit unknown link.
- SLO budget: `reliability/slo.py` consumes only evidenced signals
  (latency p*, error rate, availability); missing signal →
  budget UNKNOWN, never interpolated. Test asserts unknown over
  fabrication.
- `docs/security-reliability.md` updated with the adversarial
  coverage matrix and honest-boundary table.
- pytest/ruff/mypy/lab pass — corpus precision must not regress.

# Constraints

- No new check-id families without a real evidence source; extend
  existing catalogs with rationale comments.
- Every "no finding" test must additionally assert the analysis
  produced entities — silence is not correctness.
- Amplification math stays deterministic; no probabilistic models.
