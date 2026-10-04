---
id: 053-plugin-registry
title: Plugin manifest + registry — discovery, trust classes, plugins CLI
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §50-§53.
- Problem: `plugins/trust.py` has TrustClass + load_plugin that never
  executes untrusted code, but there is no manifest format, no
  discovery/metadata/activation/conflicts registry, no CLI.
- Out of scope: signing infra (SIGNED class exists; verification is a
  trust-level record, not crypto — spec 069 handles provenance);
  third-party plugin hosting.
- Review failure: importing a plugin module to read its metadata;
  trust classes that can be elevated by the plugin itself; a registry
  silently dropping incompatible plugins.
- Riskiest assumption: manifest format — RESOLVED:
  `forge-doctor-plugin.toml` (or `[tool.forge-doctor]` in
  pyproject.toml) — plugin_id, version, doctor_api compat range,
  capabilities, trust_class declared AND re-validated: anything not
  BUILTIN/APPROVED_LOCAL/SIGNED-verified → UNTRUSTED, never executed.
- Smallest acceptable: `PluginManifest` model + `PluginRegistry`
  (discover via entry-points + local dir scan) + `plugins
  list/inspect` CLI + tests incl. an untrusted plugin never imported.

# Context

§51 manifest: plugin id, version, doctor_api compatibility,
capabilities, trust_class. §52 registry: discovery, metadata,
compatibility, capabilities, trust, activation, conflicts. §53:
UNTRUSTED never executed.

# Acceptance Criteria

- `plugins/manifest.py`: `PluginManifest` frozen model + strict
  TOML parse (tomllib); validation errors → manifest rejected with
  reasons, never partial trust.
- `plugins/registry.py`: `PluginRegistry` — discover (installed
  entry-points `forge_doctor_api.plugins` + `plugins/` dir manifests),
  `list()`, `get(plugin_id)`, `compatible(manifest)` vs sdk_version,
  `activate(plugin_id)` (trust-gated: UNTRUSTED → error, never
  import), `conflicts()` (capability/id collisions surfaced).
- CLI `plugins list` (id, version, trust, compat, capabilities) +
  `plugins inspect <id>` (manifest + rejection reasons) +
  `plugins verify <id>` (compat + conformance preflight).
- Trust invariant test: an UNTRUSTED plugin's module is never
  imported even under `activate` attempts (import-tracking assert).
- pytest/ruff/mypy pass.

# Constraints

- Manifest parsed as data only; plugin modules import ONLY on
  activate by a trusted class.
- No new runtime deps (tomllib stdlib).
