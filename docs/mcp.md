# MCP server

forge-doctor-api serves the Doctor over the Model Context Protocol.
The transport is stdio — fully offline; a socket-blocked environment
still speaks the protocol.

```bash
pip install 'forge-doctor-api[mcp]'
forge-doctor-api mcp services/orders            # stdio
forge-doctor-api mcp services/orders --transport stdio
```

A missing `mcp` extra exits 2 with the install hint
(`McpDependencyError` — never a bare `ModuleNotFoundError`).

## Boundary contract

The MCP surface is a hardened boundary, not a raw passthrough:

- **Errors are data.** Tool failures return compact JSON
  `{"error": {"code", "message"}}` with stable codes:
  `DOMAIN_ERROR` (typed `DoctorError`), `INTERNAL_ERROR` (unexpected
  failure — class names, paths, and tracebacks never reach the wire),
  `RESPONSE_TOO_LARGE` (payload over budget with no truncatable
  collection). Protocol-layer failures — unknown tools, invalid or
  missing arguments — return `isError: true` results from the MCP
  layer itself.
- **Responses are bounded.** Payloads over `MCP_RESPONSE_BUDGET`
  (256 KiB) are deterministically truncated — largest top-level
  collections first, order preserved — and every cut is recorded as an
  `UnknownFact` of `kind: "truncated"` in an `unknowns` field.
  Nothing is dropped silently.
- **Output is deterministic.** Compact JSON text, sorted keys, no
  timestamps. Tools return JSON text content (`structured_output`
  disabled), preserving the `doctor.*` wire contract across MCP
  library versions.
- **Inventory is frozen.** `factory/artifacts/mcp-inventory.json`
  pins tool names, input-schema digests, and `doctor://` resources;
  `python factory/mcp_inventory.py --check` fails on drift.
- **Install smoke.** `python factory/mcp_smoke.py` drives a real
  stdio handshake (initialize → tools/list → tools/call) against the
  executable — wired into CI against the built wheel.

## Tools

| Tool | Returns |
|---|---|
| `doctor.scan` | full deterministic scan report |
| `doctor.get_service` | service summary: titles, versions, op counts |
| `doctor.get_api` | contract surface: methods + paths |
| `doctor.get_contract` | contract metadata (doc identity + versions) |
| `doctor.get_clients` | outbound client call surface |
| `doctor.get_runtime` | runtime DomainSummary (null w/o evidence) |
| `doctor.get_security` | security model findings |
| `doctor.get_reliability` | reliability model status |
| `doctor.get_findings` | all scan findings |
| `doctor.get_unknowns` | explicit unknowns across models |
| `doctor.get_breaking_changes` | breaking contract changes |
| `doctor.get_blast_radius` | blast radius over breaking changes |
| `doctor.get_capabilities` | detected capabilities |
| `doctor.get_graph` | graph DomainSummary or null |
| `doctor.get_handoff` | V2 ApiHandoffBundle |
| `doctor.get_operation` | one operation by `operation_id` |
| `doctor.explain` | one finding by `finding_id` + evidence + why |

All tools return compact deterministic JSON text — no payloads, no
raw spans, no schema bodies.

## Resources

| URI | Slice |
|---|---|
| `doctor://service` | ops + finding ids for the service |
| `doctor://graph` | bounded graph projection |
| `doctor://unknowns` | all UnknownFacts |
| `doctor://service/{sid}` | one service slice |
| `doctor://operation/{op}` | operation + related findings |
| `doctor://finding/{ref}` | one finding + evidence + unknowns |
| `doctor://handoff/{hid}` | V2 bundle by handoff id |

Templated reads for unknown ids return a valid, honestly empty slice
(`findings: []`, `unknowns: []`) — the resource exists even when the
subject does not.
