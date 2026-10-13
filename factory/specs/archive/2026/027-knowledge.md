---
id: 027-knowledge
title: Knowledge packs, provenance, capability packs, plugin SDK trust boundary
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §69, §70, §126–§132, §193.
- Problem: standards/framework knowledge must be versioned data (bundled, offline) so behavior updates without code changes.
- Out of scope: live doc fetching (§129 forbids), third-party plugin runtime loading — SDK + trust classes only.
- Review failure: knowledge embedded in code constants (must live in packs), mutable fact without provenance, untrusted plugin path executable by default.
- Riskiest assumption: pack schema design — RESOLVED: YAML pack documents under `knowledge/` with `source`, `source_version`, `last_verified`, `effective_since`, `deprecated_since` provenance fields per §127; loader validates schema.
- Smallest acceptable: `knowledge/` tree + loader + provenance model + standards packs (OpenAPI/OWASP) + `Capability`/`CapabilityDependency` engine + plugin trust classes.

# Context

Knowledge supply chain (§126): `knowledge/openapi|asyncapi|graphql|grpc|security|frameworks|gateways/`. Every mutable fact carries provenance (§127): source, source_version, last_verified, effective_since, deprecated_since. Initial standards (§128): OpenAPI 3.0/3.1/3.2, AsyncAPI 2/3, GraphQL spec, gRPC behaviors, OWASP API Top 10, HTTP semantics, JSON Schema — bundled/versioned, never fetched live (§129). Capability engine (§69): OPENAPI_32, GRAPHQL_SUBSCRIPTIONS, GRPC_STREAMING, MTLS, RATE_LIMITING, RETRY, HEDGING, HEALTH_CHECK, ASYNCAPI, WEBHOOK, IDEMPOTENCY_KEYS + dependencies (§70: SAFE_RETRY REQUIRES IDEMPOTENT_OPERATION; GRPC_CLIENT_HEALTH REQUIRES HEALTH_SERVICE). Capability packs (§130). Plugin SDK (§131): FrameworkAdapter/GatewayAdapter/ContractAdapter/RuntimeAdapter/SecurityRulePack with trust boundary (§132): BUILTIN, SIGNED, APPROVED_LOCAL, UNTRUSTED. Domain maturity stages tracked internally (§193).

# Acceptance Criteria

- `knowledge/` directory tree per §126 with YAML pack files; loader validates pack schema + provenance fields (§127).
- Initial packs: OpenAPI 3.0/3.1/3.2 feature/version facts, OWASP API Top 10 2023 mapping (consumed by spec 018), HTTP semantics basics, JSON Schema notes — each entry sourced+versioned.
- Capability engine (§69): `Capability` detection from models/config; `CapabilityDependency` rules per §70 evaluated to surface capability gaps (e.g. retry enabled without idempotency evidence).
- Capability packs (§130) mapping platform/framework → known capabilities.
- Plugin SDK interfaces (§131) as typed protocols; trust classification (§132) — UNTRUSTED plugins are listed but never loaded.
- Knowledge version surfaced in every exported payload (§174: `knowledge versions`).
- Tests per §202 incl. malformed packs, missing provenance, stale `last_verified`.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- No live doc/spec fetch during scan — packs are bundled and versioned (§129).
- Knowledge is data; checks read packs instead of hardcoding standard facts.
- UNTRUSTED code is never imported/executed (§132).

# Review Notes

- Verify OWASP pack drives spec 018's category mapping (no duplicated constants).
- Confirm provenance appears in serialized outputs where facts came from packs.
