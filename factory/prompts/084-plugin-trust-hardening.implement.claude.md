You are implementing Loop Factory spec `084-plugin-trust-hardening`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\084-plugin-trust-hardening.md`
        Spec hash: `ba87fecf4a8b112670d291ca93ad02f643c17aea833f169574380fb1a3887f45`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
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
