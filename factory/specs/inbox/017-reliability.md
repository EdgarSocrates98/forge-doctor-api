---
id: 017-reliability
title: Reliability model — timeouts, retries, idempotency, circuit breakers, SLO
agent: claude
risk: high
grill: required
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m forge_doctor_api reliability inspect --help
---

# Grill Gate

- Owner: project owner; decisions sourced from §39–§47, §154, §156–§158, §228.
- Problem: retry amplification, impossible timeout budgets, unproven idempotency — third demo target (§228).
- Out of scope: live failure injection, mesh control-plane writes, remediation execution (022 classifies fixes only).
- Review failure: amplification computed without explicit configs (§41 forbids), POST assumed non-idempotent / PUT assumed idempotent (§42 forbids), health endpoint inferred not discovered (§157).
- Riskiest assumption: config-source coverage for retry/timeout evidence — OPEN: confirm first pass = gateway/envoy-style config + framework annotations + service config, with mesh (Istio/Linkerd) deferred per §73.
- Smallest acceptable: `ApiReliabilityModel`, `RetryPolicy`, amplification math (explicit configs only), `IdempotencyEvidence`, `TimeoutBudget`, RELAPI### checks, SLO + error budget.

# Context

`ApiReliabilityModel` (§39): timeout, deadline, retry, backoff, jitter, circuit_breaker, bulkhead, idempotency, cache, fallback, health_check, load_balancing. `RetryPolicy` (§40): max_attempts, backoff, jitter, retryable_statuses, timeout, scope. Amplification multiplies stacked explicit configs only (§41 — gateway 3 × service 3 × client 3 = 27). `IdempotencyEvidence` sources (§42): HTTP method, idempotency key, framework config, handler semantics, db uniqueness, contract metadata. `TimeoutBudget` detects impossible budgets (§43); deadline propagation for gRPC + s2s HTTP (§44). Circuit breakers from Resilience4j/Envoy/Istio/mesh/app-libs (§45). `ApiServiceObjective` (§46) + `ErrorBudget` — only with sufficient data (§47). LB model (§156), health checks (§157), graceful shutdown config evidence (§158).

# Acceptance Criteria

- `ApiReliabilityModel` + `RetryPolicy` models per §39–§40 populated from declared config/contract/framework evidence — sources recorded per field.
- Retry-amplification computation across stacked hops (client→gateway→service→deps); only when explicit per-hop configs exist; otherwise UNKNOWN with missing-evidence list (§41).
- `IdempotencyEvidence` aggregation per §42 sources; verdict = evidence-backed or UNKNOWN — HTTP method alone never decides.
- `TimeoutBudget` (§43): compare client timeout vs downstream budgets; flag impossible budgets (sum of downstream needs > caller budget) with RELAPI### findings.
- Deadline-propagation detection for gRPC/s2s HTTP call chains (§44).
- Circuit-breaker config extraction (Resilience4j + Envoy-style config first; Istio/mesh adapter interface reserved, §45/§73).
- `ApiServiceObjective` (§46) + `ErrorBudget` (§47) — emitted only when window/data suffices; else UNKNOWN.
- LB model (§156); gRPC standard health protocol recognized, HTTP health endpoints modeled only when explicitly discovered (§157); graceful-shutdown config evidence (§158).
- RELAPI### findings namespace (§218); CLI `reliability inspect` / `reliability path` (§164).
- Demo §228 reproducible: gateway retry=3 + service retry=3 + non-idempotent payment op → "retry amplification candidate + idempotency unknown + manual review required".
- Tests per §202; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- Explicit-config-only amplification (§41); no assumed defaults.
- No assumptions about HTTP-method idempotency without context (§42).
- Evidence hierarchy respected: config evidence ≠ runtime confirmation (§102).

# Review Notes

- Verify amplification math includes per-hop retryable-status overlap only when policies declare them.
- Confirm "impossible budget" accounts for sequential vs parallel downstream calls.
- Check error-budget math guards against insufficient windows (§47).
