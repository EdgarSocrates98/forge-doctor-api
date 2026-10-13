---
id: 084-plugin-trust-hardening
title: Plugin trust hardening — import-gating proof, failure matrix, result validation
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
  Phase 4 and item §25.
- Problem: trust classes and a conformance suite exist, but the
  trust boundary is not proven end to end: no AST-level guarantee
  that untrusted code is never imported, incomplete dynamic-failure
  coverage, no mutation proof for plugin listing/verify/doctor, and
  no output-schema validation of plugin results.
- Out of scope: real signature cryptography (roadmap), a plugin
  marketplace, running untrusted code in-process safely (never —
  untrusted stays unimported).
- Review failure: a proof that only checks `import` statements and
  misses `__import__`/`importlib`; mutation checks that hash only
  manifests; output validation that accepts any dict.
- Riskiest assumption: an AST gate can keep working as the plugin
  system grows — RESOLVED: allowlist import sites (registry loader)
  + whole-src AST test banning import-of-plugin outside the
  allowlisted loader.
- Smallest acceptable: import-gating AST test, 9-case dynamic
  failure matrix, no-network + no-mutation proofs, output
  validation rejects invalid severity/entity-id/finding/
  evidence-kind/out-of-root path/unknown schema version, docs.

# Context

Phase 4. Existing: `plugins/manifest.py` (strict parse, trust
revalidation), `registry.py` (discovery without import, conflicts),
`trust.py` (4 classes, BUILTIN under package), `conformance.py`
(6 behavioral checks incl. offline + side-effects), `test_boundary.py`
AST purity. Missing: proof that trust precedes import globally,
failure matrix, mutation proof for read-only plugin commands,
output contract validation.

# Acceptance Criteria

- `tests/test_plugin_boundary.py`: AST scan proves no `import` /
  `importlib` call anywhere in `src/` can reach a plugin module
  except through the registry's trust-gated loader (the loader is
  the single allowlisted import site; it checks trust first).
- Dynamic failure matrix tests: plugin success; import failure;
  wrong `doctor_api` version; invalid manifest; duplicate plugin
  id; analysis timeout (document if cooperative — no threads, so
  wall-clock-free cooperative budget or documented absence);
  invalid JSON/non-`Model` result; oversized result (recorded
  unknown, bounded); plugin crash → typed error surface, no
  traceback leak.
- No-network proof: `plugins list|verify|doctor|conformance` run
  under `socket.*` patched to raise — all pass.
- No-mutation proof: sha256 tree of a fixture root identical
  before/after `plugins list`, `plugins verify`, `plugins doctor`,
  and `run_conformance`.
- Output validation (`plugins/validation.py` or extension of
  conformance): reject plugin output containing invalid severity,
  non-canonical entity id, malformed Finding (no evidence),
  unknown evidence kind, `file` path outside the analyzed root,
  or unknown `schema_version`; each rejection is a typed error,
  listed in a test per case.
- `docs/plugins.md` (extend): the five adapter surfaces that
  actually exist (FrameworkAdapter, GatewayAdapter, RuntimeAdapter,
  ContractAdapter, SecurityRulePack — adjust to what the code
  exposes), trust classes table, conformance checks table, failure
  taxonomy, and the "trust precedes import" invariant.
- Architectural purity: extend the boundary AST test — no import
  of `forge_doctor_data`, no API-Forge/Forger orchestration module
  names, anywhere in `src/`.
- pytest/ruff/mypy pass.

# Constraints

- Untrusted plugin code is never imported — the test proves the
  invariant, it does not create a sandbox.
- Timeout semantics must be honest: if the loader is synchronous,
  document that timeouts are enforced at the conformance harness
  level, not per-plugin-call.
- No new runtime deps.
