---
id: 018-security
title: Security intelligence — OWASP API Top 10 passive analysis
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m forge_doctor_api security inspect --help
---

# Grill Gate

- Owner: project owner; decisions sourced from §48–§57, §115–§120, §124–§125, §198, §229.
- Problem: passive security-risk surface from contract/config/runtime artifacts — fourth demo target (§229).
- Out of scope: active scanning, probing, exploitation, DAST of any kind (§1 — never offensive scanning).
- Review failure: any "vulnerability confirmed" language from static analysis (§50 forbids), business-flow inference without declared evidence (§120), sensitive-category guessing by name (§124).
- Riskiest assumption: which APISEC checks ship first — RESOLVED: APISEC001–010 as listed (contract/config evidence) + authn/authz models + CORS/rate-limit/TLS evidence + redaction audit. Unsafe-consumption (§116) and business-flow (§120) ship candidate-level only, matching acceptance criteria.
- Smallest acceptable: `ApiSecurityModel`, OWASP mapping, auth models, APISEC001–010, redaction guarantee, demo §229.

# Context

Security is passive: static, configuration-based, contract-based, runtime-artifact-based (§1, §48). `ApiSecurityModel` maps to OWASP API Security Top 10 2023 (§49) — all ten categories tracked as knowledge; detection only via evidence. Finding classification (§49): `candidate | configuration risk | evidence-backed issue | unknown`. `AuthenticationScheme` types (§51), `AuthorizationPolicy` (§52), auth drift across OpenAPI-security/middleware/gateway-policy (§53), `RateLimitPolicy` (§54), CORS (§55), TLS/mTLS config evidence only (§56), secret hygiene + output redaction (§57, §125). Unsafe-consumption (§116), webhooks (§117), pagination (§118), resource-consumption (§119), business-flow protection only with declared/policy evidence (§120), data classification only via explicit metadata (§124).

# Acceptance Criteria

- `ApiSecurityModel` with OWASP API Top 10 2023 category mapping (§49); each finding carries the four-level classification — never "confirmed vulnerability" from static evidence (§50, §229).
- `AuthenticationScheme` (§51: OAuth2, OIDC, JWT, API_KEY, BASIC, MTLS, SESSION, CUSTOM, NONE, UNKNOWN) extracted from contracts + implementation + gateway config.
- `AuthorizationPolicy` (§52): operation, roles, scopes, claims, ownership_check, evidence.
- Auth-drift comparison across the three evidence planes (§53) → findings.
- `RateLimitPolicy` (§54) + CORS model (§55: origins/credentials/methods/headers, wildcard detection) + TLS/mTLS config-evidence detection (§56).
- APISEC001–010 per §50: object-ID route without authorization evidence; admin operation without explicit authorization evidence; unauthenticated sensitive operation; wildcard CORS candidate; missing rate-limit evidence on public operation; unrestricted expensive operation; unsafe outbound URL consumption candidate; sensitive property exposed unexpectedly; deprecated undocumented API still reachable; unsafe third-party API dependency configuration.
- `WebhookModel` (§117: signature-verification, replay-protection, idempotency, retry evidence); pagination model (§118) + unbounded-list check; resource-consumption signals (§119); `SensitiveBusinessFlow` only when declared/policy evidence exists (§120); data classification only from explicit metadata (§124).
- Redaction enforcement on all outputs (§57/§125) — test proves no token/secret leakage through findings.
- CLI `security inspect` (§163); demo §229 reproducible: public endpoint + object-id param + no authz evidence → "BOLA risk candidate", NOT "BOLA vulnerability confirmed".
- Tests per §202 incl. adversarial FP cases; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- Passive only — never scan, probe, or attack (§1).
- Every finding = candidate/configuration risk/evidence-backed/unknown; "confirmed" requires evidence-backed chain, never static-only (§49–§50).
- No sensitive-category inference by property names without explicit metadata (§124).
- Redaction cannot be disabled by default (§57).

# Review Notes

- BOLA check (APISEC001): verify it needs object-id-shaped param + missing authz evidence, and emits *candidate* — demo §229 wording is the contract.
- Confirm object-property exposure (APISEC008) compares declared schema vs observed/impl response fields.
- Check OWASP mapping is knowledge-pack-driven (§128) so categories update without code changes.
