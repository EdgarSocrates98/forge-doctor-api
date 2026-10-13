# Plugins

forge-doctor-api has a plugin surface, but the trust boundary is the
product: **untrusted plugin code is never imported.** Manifests are
data, not code; trust is re-validated, never taken on the plugin's
word; and there is exactly one dynamic-import call site in the whole
package — the trust-gated loader.

## Trust classes

| Class | Requirement | Loadable? |
|---|---|---|
| `BUILTIN` | module must resolve inside `forge_doctor_api` | yes |
| `SIGNED` | manifest carries a `signature` verification record | yes |
| `APPROVED_LOCAL` | manifest carries an explicit local `source` path | yes |
| `UNTRUSTED` | default — missing, misspelled, or self-elevated evidence | **never** |

`UNTRUSTED` plugins are listed and inspectable (inventory, review,
operator action) but `activate()` refuses them before any import.
Self-elevation is impossible: declaring `BUILTIN` for a module outside
the package degrades to `UNTRUSTED` with a recorded rejection.

## Adapter surfaces

Five typed protocols in `forge_doctor_api.plugins.sdk` define what a
plugin may implement:

| Protocol | Surface |
|---|---|
| `FrameworkAdapter` | `scan(ctx, service, paths)` → `RouteScan` |
| `GatewayAdapter` | `routes(ctx, files)` → gateway-declared routes |
| `ContractAdapter` | `load(ctx, paths)` → contract domain model |
| `RuntimeAdapter` | `detect`, `iter_spans`, `iter_summaries` over runtime artifacts |
| `SecurityRulePack` | `check_specs()` → extra security checks |

## Commands

```bash
forge-doctor-api plugins list     --dir plugins   # manifests + rejections + conflicts
forge-doctor-api plugins inspect  <id>            # one manifest as JSON
forge-doctor-api plugins verify   <id> <project>  # trust gate + conformance run
```

All are offline (proved under blocked sockets) and read-only (proved
by before/after sha256 tree equality).

## Conformance checks

`plugins verify` runs the conformance suite — structural and
behavioral detectors, honestly documented as bypassable by a plugin
that detects the harness:

| Check | Fails when |
|---|---|
| `determinism` | two runs over the same tree serialize differently |
| `offline` | the run raises under blocked sockets |
| `evidence` | a Finding lacks evidence, or UNKNOWN lacks unknowns |
| `side-effects` | the project fileset (paths + sha256) changed |
| `output-compat` | the result does not round-trip as JSON |
| `unknown-semantics` | unknowns are not real `UnknownFact`s |
| `output-schema` | the serialized result violates `plugins/validation.py` |

### Output validation rules

`plugins/validation.py` validates the *serialized* result — plain
dicts cannot bypass model invariants. Rejected cases: invalid
severity/confidence/evidence-kind, non-canonical check id or entity
id, findings without evidence, UNKNOWN confidence without unknowns,
`source_location` paths escaping the analyzed root, unknown
`schema_version`, non-mapping results, and serialized output over
`PLUGIN_RESULT_BUDGET` (256 KiB).

## Failure taxonomy

| Failure | Surface | Behavior |
|---|---|---|
| Invalid manifest | `parse_manifest` / registry | typed `ManifestError`, listed as rejection |
| Duplicate plugin id | `registry.conflicts()` | `PluginConflict(kind="duplicate-id")` |
| `doctor_api` mismatch | `activate()` | `ModelError` naming required + actual |
| UNTRUSTED activation | `activate()` | `ModelError`; module never imported |
| Import failure | `load_plugin` | `ModelError`; nothing enters `sys.modules` |
| No run surface | `plugins verify` | exit 2 — no `analyze`/adapter callable |
| Plugin crash | `run_conformance` | `run` check = `error`, no traceback leak |
| Bad output | `output-schema` check | typed `OutputViolation`s, sorted |

There is no per-call wall-clock timeout: the plugin surface is
synchronous (no threads, no asyncio) — enforced by AST test. A
runaway plugin is a *conformance harness* concern (run it under an
external deadline), documented rather than faked.

## Invariants (enforced by `tests/test_plugin_boundary.py`)

- **Trust precedes import:** every `import_module`/`__import__` call
  in `src/` is either `plugins/trust.py` (the gate) or a literal
  `forge_doctor_api.*` first-party target. A plugin module path can
  only be reached through `activate()` → `load_plugin()`.
- **No external orchestration imports:** `forge_doctor_data`,
  `forger`, `api_forge`, and orchestration roots are banned anywhere
  in `src/`.
- **Discovery is data-only:** entry-point metadata and manifest TOML
  are parsed without importing plugin modules.
