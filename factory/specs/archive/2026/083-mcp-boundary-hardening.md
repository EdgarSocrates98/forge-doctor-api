---
id: 083-mcp-boundary-hardening
title: MCP boundary hardening — error matrix, inventory freeze, bounded payloads, wheel smoke
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 3 and items §5/§18.
- Problem: `handoff/mcp_server.py` exists and tools/resources work,
  but the MCP surface is not proven as a boundary: no stable error
  contract for non-DoctorError failures, no frozen tool inventory
  gate, no bounded-payload truncation semantics, no cross-surface
  consistency proof, no wheel-installed MCP smoke.
- Out of scope: new tools, resource shapes, streaming transports,
  authn/z at the MCP layer.
- Review failure: error handling that only covers `DoctorError` and
  leaks Python tracebacks; an inventory file that no test enforces;
  truncation that silently drops entities.
- Riskiest assumption: bounded responses can preserve the
  most-relevant entities deterministically — RESOLVED: reuse the
  handoff bundling budget machinery (sorted truncation + recorded
  UnknownFact) rather than inventing a second policy.
- Smallest acceptable: 12-case JSON-RPC matrix, stable error
  contract, frozen tool inventory + regression test, bounded payload
  with recorded unknown, cross-surface consistency test, wheel MCP
  smoke script + CI step.

# Context

Phase 3. Existing: `mcp_server.py` lazy-imports `mcp`, registers
~17 `doctor.*` tools + `doctor://` resources, compact deterministic
JSON, `doctor.explain` converts `DoctorError` to typed output;
`handoff/boundary.py` already bounds bundles with unknowns. Missing:
error contract for the rest of the failure space, inventory freeze,
budget on MCP responses, consistency proof, wheel smoke.

# Acceptance Criteria

- `tests/test_mcp_boundary.py` covers the full matrix: valid
  initialize; unsupported protocol version; unknown method; missing
  params; invalid params; unknown resource; empty result; large
  result (over budget → bounded); bounded result records an
  UnknownFact naming the truncation; internal exception inside a
  tool → stable error, no traceback; malformed JSON; invalid
  JSON-RPC envelope (missing jsonrpc/id).
- Stable error contract: every failure path returns/raises a typed
  error with stable `code` + `message` (and optional evidence refs);
  a test asserts no Python exception type name leaks into error
  messages for the malformed/unknown-method/unknown-resource cases.
- `factory/mcp_inventory.py` or data file `src/forge_doctor_api/
  handoff/mcp_inventory.json`: frozen list of tool name + input
  schema digest + stability + version; a test regenerates it from
  the live server and diffs — inventory drift fails the suite.
- Bounded payloads: tool responses over `HANDOFF_BUDGET`-style
  budget truncate deterministically (sorted entities/findings,
  lowest-confidence-first or stable order — document choice) and
  append an UnknownFact; never silent.
- Cross-surface consistency test: one fixture project scanned via
  CLI JSON, SDK `Doctor.scan`, MCP `doctor.scan`, and handoff
  bundle — assert identical finding identities (id + fingerprint/
  entity ids), severity, confidence, evidence refs, and that
  unknown semantics survive all four surfaces.
- `factory/mcp_smoke.py`: stdlib script that spawns the MCP stdio
  server from an installed wheel, performs initialize + tools/list
  + 3 representative calls, asserts stable shapes; wire into
  `quality.yml` full job as a wheel smoke step.
- `docs/mcp.md` updated: tool inventory table with stability class,
  error contract section, bounded-payload semantics, transport
  note.
- pytest/ruff/mypy pass.

# Constraints

- `mcp` stays an optional extra; minimal install must keep working
  — server module imports lazily.
- No new runtime deps.
- Truncation order must be documented and deterministic.
