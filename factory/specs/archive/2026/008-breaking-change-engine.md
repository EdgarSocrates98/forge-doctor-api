---
id: 008-breaking-change-engine
title: ApiCompatibilityEngine — semantic diff and breaking changes
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m forge_doctor_api contract compatibility --help
---

# Grill Gate

- Owner: project owner; decisions sourced from §16, §66, §121, §122, §123, §160, §179, §180, §226.
- Problem: classify whether a contract change breaks clients — the central v0.1 feature and first demo target (§225 Phase H, §226).
- Out of scope: client-usage-aware impact upgrade (spec 009 upgrades POTENTIALLY_BREAKING→confirmed), GraphQL/proto schema compat rules beyond the unified engine's extension points (012/013).
- Review failure: requesting-side vs response-side compat conflated (§123), missing UNKNOWN class, nondeterministic diff, demo §226 not reproducible.
- Riskiest assumption: rule table for §16.2 covers realistic schema diffs — mitigate via adversarial fixtures + UNKNOWN fallback instead of guessing.
- Smallest acceptable: two OpenAPI docs → semantic diff → classified changes + `contract diff`/`contract compatibility` CLI, demo §226 reproducible.

# Context

Phase H (§225). `ApiCompatibilityEngine` (§16) classifies changes as `NON_BREAKING | POTENTIALLY_BREAKING | BREAKING | UNKNOWN`. Request compatibility and response compatibility are *separate* semantics (§123). Field identity uses explicit schema paths (§122). The `SchemaCompatibilityEngine` is designed as the unified engine for JSON Schema/OpenAPI now, GraphQL/Protobuf/AsyncAPI later (§121). Contract fingerprints (§179–§180) enable baseline comparisons stable across formatting/ordering/comments. `forge-doctor-api diff --semantic` (§66) and §160 contract CLI surface here.

# Acceptance Criteria

- Semantic diff of two `OpenApiProjectModel`s / documents → typed change list (endpoints, methods, params, schemas, enums, status codes, auth, content-types).
- `BREAKING` rules per §16.2: removed endpoint; removed method; required parameter added; parameter removed; parameter type changed; request field required; response field removed; response type narrowed; enum value removed; status code removed; auth requirement tightened; content-type removed.
- `POTENTIALLY_BREAKING`/non-breaking candidates per §16.3 (optional response field added, new endpoint, new optional query param, enum value added) — flagged as non-universally-safe when client semantics unknown.
- `UNKNOWN` emitted when evidence is insufficient — never guessed (§16.1).
- Request vs response direction handled separately in schema compat (§123): request-side widening/narrowing vs response-side.
- `SemanticFingerprint` (§180): stable across formatting, ordering, comments — powers §179 compatibility baseline storage.
- CLI: `forge-doctor-api contract diff`, `contract compatibility`, and `diff --semantic` produce structured output (console + JSON) per §160/§175.
- `COMPAT###` findings namespace (§218).
- Demo §226 reproducible end-to-end: FastAPI service + openapi.yaml + removed `email` response field → breaking contract change on `getUser`.
- Tests per §202; schema-diff adversarial cases (type unions, oneOf/anyOf, additionalProperties).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Deterministic diff ordering — same inputs → identical output.
- Don't mark "safe" by default: additions are candidates, not guarantees, when client semantics unknown (§16.3).
- No client-code analysis here — spec 009 consumes breaking changes.

# Review Notes

- Verify narrowing/widening direction logic on both request and response sides (§123) — this is the classic bug.
- Check enum/oneOf/anyOf diffs don't produce duplicate or contradictory findings.
- Confirm fingerprint stability across YAML↔JSON formatting of the same contract.
