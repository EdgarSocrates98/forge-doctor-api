---
id: 045-mcp-server
title: Real MCP server — stdio transport, tools, resources
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §29-§30.
- Problem: `handoff/mcp.py` is a typed local API with no transport —
  an MCP client cannot call it. §29 requires a real server,
  stdio-first, HTTP only as optional external layer.
- Out of scope: Streamable HTTP transport (flagged optional, deferred —
  adds a server dependency and a network surface to an offline-first
  tool; decision documented in docs/roadmap.md).
- Review failure: a subprocess-wrapping hack masquerading as a server;
  pulling a network stack into core; tools returning raw payloads
  instead of compact refs.
- Riskiest assumption: MCP dependency — RESOLVED: `mcp` python package
  as an *optional* extra (`pip install forge-doctor-api[mcp]`), guarded
  import; core has zero new deps and the command fails with a clear
  "install extra" message when absent.
- Smallest acceptable: `forge-doctor-api mcp` (stdio), tool set
  doctor.scan + core getters, resource URIs doctor://*, protocol tests
  via the SDK's in-process client.

# Context

§29 flow: MCP client → tools/resources → typed request → deterministic
analysis → compact context → typed response. §30 tools list; resources
doctor://service/{id} etc. §111: dependency additions need
justification — mcp is optional-extra, never imported by core.

# Acceptance Criteria

- `cli.py` `mcp` command: `--transport stdio` default; clear error if
  `mcp` extra missing (exit 2 + install hint).
- `handoff/mcp_server.py` (or `mcp/` package): server exposing tools —
  doctor.scan, get_service, get_api, get_operation, get_contract,
  get_clients, get_runtime, get_security, get_reliability,
  get_findings, get_unknowns, get_breaking_changes, get_blast_radius,
  get_capabilities, get_graph, get_handoff, explain — each delegating
  to the Doctor facade/DoctorApi, returning compact serialized models.
- Resources: `doctor://service/{id}`, `doctor://operation/{id}`,
  `doctor://finding/{id}`, `doctor://graph`, `doctor://unknowns`,
  `doctor://handoff/{id}` serving JSON slices.
- Tests: protocol handshake via mcp test client, tool schema
  validation, per-tool call+serialization round trip, determinism
  across two calls, offline (socket-blocked server still works on
  stdio).
- docs/mcp.md; pytest/ruff/mypy pass.

# Constraints

- Optional dependency only: `mcp` in `[project.optional-dependencies]`.
- Compact outputs — same payload policy as handoff.
