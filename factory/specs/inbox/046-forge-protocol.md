---
id: 046-forge-protocol
title: Forge Protocol — typed cross-product contracts, versioned
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §25-§28, §116.
- Problem: cross-product flow (The Forger → Doctor → API Forge) has no
  typed protocol — handoff is a bundle, not a request/response/result
  contract with identities, capabilities, refs and receipts.
- Out of scope: actual transport/routing to other products (this repo
  defines the Doctor side contracts + produces/consumes them locally);
  the TheForgerContract boundary surface (spec 070).
- Review failure: contracts coupled to internal models so they cannot
  be versioned independently; refs that are not resolvable; a protocol
  that presumes an orchestrator rather than accepting one.
- Riskiest assumption: granularity — RESOLVED: the §26 model list
  verbatim (ForgeRequest/Capability/ContextRef/EvidenceRef/FindingRef/
  UnknownRef/Handoff/Receipt/Result/Route), each a frozen versioned
  model with `protocol_version`.
- Smallest acceptable: `forge_protocol.py` models + serializers +
  build/consume round-trip tests + docs/forge-protocol.md.

# Context

§25: deterministic request → analysis → handoff → implementation →
receipt/result. §26 model list. §27: versioned, serializable,
dependency-light, typed, explicit boundaries, reusable across
products.

# Acceptance Criteria

- `handoff/protocol.py` (or `protocol/` package): the §26 models as
  frozen Models — ForgeRequest{protocol_version, request_id, target,
  requested_capabilities, clock}, ForgeCapability{name, status,
  unknowns}, ForgeContextRef/EvidenceRef/FindingRef/UnknownRef
  {ref_id, kind, entity?, sha256?, summary}, ForgeHandoff{handoff_id,
  bundle_ref, refs...}, ForgeReceipt{analysis_rev, handoff_id,
  consumer, result_link}, ForgeResult{status, summary, refs},
  ForgeRoute{route_id, source, destination, capability}.
- `protocol_version = 1`; `to_dict`/`to_json` deterministic;
  `parse_*` strict validation (unknown fields rejected unless marked
  extension namespace `x-*`).
- Builders: `build_request`, `build_handoff(report, bundle)`,
  `build_receipt`, `build_result` — all deterministic, clock-injected.
- Unknowns: ForgeCapability/ForgeHandoff can carry UnknownRef lists;
  nothing fabricates a capability.
- Tests: full round trip request→handoff→receipt→result, version
  mismatch handling, strict parse, determinism.
- docs/forge-protocol.md boundary doc; pytest/ruff/mypy pass.

# Constraints

- No runtime deps; stdlib serialization.
- Doctor produces analysis + handoff; it does NOT route or implement.
