# Framework adapters

Static, no-execution route/capability discovery per framework.
Adapters implement the §39 `FrameworkAdapter` protocol
(`analyzers/routes/adapter.py`):

| Method | Returns |
|---|---|
| `detect` | bool — strong-marker gate (manifest/imports) |
| `attribute` | `Attribution` per file, with evidence |
| `discover_routes` | `RouteScan` (routes + attributions + unknowns) |
| `discover_auth` / `discover_schemas` / `discover_dependencies` / `discover_middleware` / `discover_error_handlers` / `discover_validation` / `discover_serialization` / `discover_client_calls` | `SurfaceResult` — sorted `SurfaceItem`s, or empty + `UnknownFact` |

An empty surface always carries an UnknownFact — absence of evidence
is explicit, never a fabricated zero. Per-framework idiom coverage is
in `docs/frameworks.md`.

## Built-in adapters

| Adapter | Source | Strategy |
|---|---|---|
| `FastApiAdapter` | Python | `ast` — comments/strings cannot parse |
| `SpringBootAdapter` | Java | `textscan` strip + annotation state machine |
| `NestJsAdapter` | TS/JS | `textscan` strip + decorator state machine |
| `ExpressAdapter` | JS | `textscan` strip + literal call extraction |

`textscan.strip_source` blanks comment and string interiors while
preserving positions: `@GetMapping` inside a comment can never route,
yet the literal inside a real annotation still resolves.
Dynamic paths (constants, template literals, concatenation) produce
`UnknownFact`s — never guesses.

`available_adapters(context, files)` returns only adapters whose
`detect()` matches; `scan_project` merges every matching adapter's
`RouteScan`. Unknown frameworks yield an unknown, not a guess.

## Plugins

`forge-doctor-plugin.toml` (or `[tool.forge-doctor.plugin]` in
pyproject.toml) declares a plugin: id, version, module, `doctor_api`
compat range, capabilities, `trust_class`. Trust is re-validated:
`BUILTIN` needs `forge_doctor_api.*`, `SIGNED` needs a signature,
`APPROVED_LOCAL` needs a source — anything else is `UNTRUSTED`
(listed, never imported).

```bash
forge-doctor-api plugins list        # manifests + rejections
forge-doctor-api plugins inspect ID  # one manifest + compat
forge-doctor-api plugins verify ID   # compat + conformance
```

`plugins verify` runs the conformance suite: determinism (two runs
byte-equal), offline (blocked sockets), evidence (findings carry
evidence; UNKNOWN confidence carries unknowns), side-effects (fileset
unchanged), output-compat (serializes), unknown-semantics (typed
UnknownFacts). These are detectors, not proofs — the boundary is
documented.
