---
id: 075-forger-boundary-hardening
title: The-Forger boundary hardening — import bans, slim request, DeltaContext
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions from stabilization prompt Phase E +
  §7, §12, §13.
- Problem: the boundary contract is documented (spec 070) but the
  enforcement is partial — AST purity covers only `boundary.py`, not
  the whole package; ForgeRequest is loose; DeltaContext exists but is
  not wired into the handoff.
- Out of scope: orchestrating multiple doctors in-repo (The Forger is
  a separate product); kernel extraction (§26 deferred).
- Review failure: a slim ForgeRequest that drops fields the consumer
  needs; handoff payload growth unbounded; delta context lossy enough
  to fabricate change.
- Riskiest assumption: DoctorEndpoint must live inside the API repo
  and can't be validated against the sibling — RESOLVED: the endpoint
  shape is a protocol dict (`{request, handoff, capabilities,
  manifest}` keys) plus conformance tests; cross-doctor compatibility
  is proven by the shared forge-contracts/1 adapter, not by importing
  the other repo.
- Smallest acceptable: package-wide AST ban list enforcement +
  tightened ForgeRequest + bounded handoff (byte/size caps with
  deterministic truncation into `unknowns`) + DeltaContext wired into
  HandoffBundle + conformance tests.

# Context

Phase E. Boundary ownership (already documented): the Doctor observes
/normalizes/detects/measures/diagnoses/classifies/scores-impact/
reports-unknowns/serves-context. It must never route/schedule/retry/
implement/generate-code/call-network/run-subprocess/dynamic-import/
execute-target-code. The Forger consumes DoctorEndpoint(request,
handoff, capabilities, manifest) — it must not know internals.

# Acceptance Criteria

- `tests/test_boundary.py` extends AST purity walk to the whole
  `src/forge_doctor_api/` package (allowlist for arg-less stdlib
  `subprocess` never present anywhere in src anyway — assert zero);
  `importlib`, `socket`, `urllib`, `http`, `requests`, `httpx`,
  `shutil`, `ctypes`, `pickle`, `exec`, `eval`, `compile`,
  `__import__`, `os.system`, `spawn*`, `fork` banned across src/ via a
  shared `_FORBIDDEN` map + allowlist table for legit uses.
- `handoff/protocol.py`: `ForgeRequest` slimmed to
  `request_id, target, capabilities, context_refs, delta?`;
  `DeltaContext` becomes first-class (baseline_ref, changed_files,
  protocol_diff). `build_request` produces the slim shape.
- `handoff/bundle.py`: `HandoffBundle` gains `bounded()` — max
  findings/entities/relationships per section (default budget);
  over-budget sections are deterministically truncated and each
  truncation appends an `UnknownFact` recording the budget.
- `DoctorBoundary.handle()` returns a `HandoffBundle` whose size is
  provably capped; `DoctorEndpoint`-style
  `{request, handoff, capabilities, manifest}` dict available via
  `boundary.endpoint_dict(request)` for The Forger's conceptual
  consumption.
- Docs: `docs/forger-boundary.md` updated with the slim request
  table, bounded budget semantics, and DoctorEndpoint shape.
- pytest/ruff/mypy pass.

# Constraints

- `bounded()` truncation must be deterministic (sorted by stable key
  first, then take N) and must record `budget_exceeded` unknowns —
  never silent drop.
