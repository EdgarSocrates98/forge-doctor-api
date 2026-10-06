# ADR-0003 — MCP server as an optional extra

- Status: accepted
- Date: 2026

## Context

The `doctor.*` MCP tool surface gives agent hosts (Claude Code,
Cursor, IDE assistants) structured access to the Doctor. But the
`mcp` package is a heavyweight optional dependency that pulls
transitives incompatible with the engine's constraints (its typing
chains reach numpy-era stubs) — and the engine itself must stay
import-clean, offline, and dependency-minimal
(typer/rich/pyyaml only).

## Decision

- The MCP server lives behind the `mcp` extra
  (`pip install forge-doctor-api[mcp]`), in
  `src/forge_doctor_api/handoff/mcp_server.py`.
- All `mcp` imports are function-level inside `build_server()`;
  failure raises a typed `McpDependencyError` telling the caller to
  install the extra.
- mypy gets a module-scoped override for the optional boundary, not a
  project-wide loosening.
- Every MCP tool is a projection over the same `Doctor` SDK facade —
  the server adds zero analysis logic of its own.

## Consequences

- The engine installs and tests clean without `mcp`; the extra is
  additive, never required.
- The import-time purity test (`no network/subprocess/socket imports
  outside the boundary module`) keeps passing because the optional
  import is lazy and quarantined.
- Docs (`docs/mcp.md`) carry the install and tool list; the surface
  tracks the SDK, not the internals.

## Alternatives

- **Bundle `mcp` as a hard dependency** — rejected: forces every
  CLI/CI consumer to carry a server framework it never runs.
- **Separate `forge-doctor-mcp` package** — rejected for now: the
  server is a thin facade; a second package adds release complexity
  without decoupling value. Revisit if the tool surface diverges.
- **Vendored minimal MCP shim** — rejected: protocol drift and
  maintenance burden for zero user benefit.
