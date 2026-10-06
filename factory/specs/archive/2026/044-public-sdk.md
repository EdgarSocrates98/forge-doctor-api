---
id: 044-public-sdk
title: Public Python SDK — Doctor facade over the unified pipeline
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §31-§33.
- Problem: `sdk.py` is an intentional placeholder; integrators must
  reach into internals (`scan_project`, `ProjectContext`) which are
  not a stability contract.
- Out of scope: async API, event streaming, plugin authoring SDK
  (`plugins/sdk.py` stays internal-facing until spec 052).
- Review failure: the facade re-implementing scan logic; public
  surface re-exporting internal unstable types; breaking
  `DoctorApi`-dependent flows.
- Riskiest assumption: surface shape — RESOLVED: `Doctor.from_path()
  .scan() -> DoctorReport` + `diff(before)` + `explain(finding_id)` +
  `graph()` + `handoff()` + `inventory()` + `capabilities()`; all
  return the frozen core models; `scan()` accepts `before=` for diff.
- Smallest acceptable: facade + stable `__all__` + py.typed marker +
  round-trip tests + docs/sdk.md.

# Context

§32 facade: Doctor.from_path(".").scan(). §33: public SDK separate
from internal modules; version schema/output/handoff/mcp/knowledge/
plugin. Internal `forge_doctor_api.mcp.DoctorApi` remains (different
audience: agent-local typed calls).

# Acceptance Criteria

- `sdk.py` implements `Doctor` facade: `from_path(root, *, clock=None,
  profile=None)`, `scan(before=None)`, `diff(before)` (delegates to
  scan), `explain(finding_id)` (finding + evidence + why), `graph()`,
  `handoff()`, `inventory()` (ArtifactInventory), `capabilities()`.
- `forge_doctor_api.__init__` exports `Doctor` + versioned public
  models; `__all__` curated; everything else documented internal.
- `py.typed` + packaging include; `sdk_version` constant.
- Errors surface as typed exceptions (project-unreadable, not-python,
  etc.) — never bare tracebacks on user input.
- Tests: round-trip all methods on lab fixture, determinism, offline,
  import-surface stability (assert __all__ snapshot).
- docs/sdk.md usage page; pytest/ruff/mypy pass.

# Constraints

- Zero new dependencies; thin delegation only.
- Public = stable; breaking changes need a major version (§33).
