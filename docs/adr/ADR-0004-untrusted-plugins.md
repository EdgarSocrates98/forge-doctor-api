# ADR-0004 — Untrusted plugins are never imported

- Status: accepted
- Date: 2026

## Context

The plugin system (specs 053–054) lets third parties declare
framework adapters and check packs. A Python plugin is arbitrary code:
importing an unvetted module would hand an attacker execution inside
the Doctor's process — violating the "no arbitrary target-code
execution" invariant and every offline/deterministic guarantee.

## Decision

- Plugins are *manifests first*: `plugins/manifest.py` validates a
  declarative `PluginManifest` (id, version, capabilities, entry
  point, checksum) before anything else happens.
- `plugins/conformance.py` verifies a plugin against the declared
  surface without importing its code: structure, signatures and
  behavior are probed through the manifest + the conformance harness,
  not `importlib`.
- Verification runs with the same offline invariants as the engine —
  the conformance suite patches socket creation to prove the plugin
  cannot phone home during verification.
- A plugin that fails manifest validation or conformance is rejected
  and recorded — never partially imported.

## Consequences

- The supply-chain boundary is explicit: trust is established
  declaratively before any code path exists.
- Conformance is itself evidence-first: a plugin either satisfies the
  contract under the harness or it is reported — no silent skips.
- Cost: plugin authors must pass the manifest schema; the Doctor
  cannot adopt arbitrary duck-typed modules.

## Alternatives

- **Import-then-inspect** — rejected: import is execution; too late
  to verify anything.
- **Sandboxed import (subprocess/container)** — rejected: the engine
  may not spawn subprocesses; out of scope for a library whose
  consumers embed it.
- **Signature/trust store (sigstore-style)** — deferred: worth
  revisiting for distribution, but manifest+conformance already
  covers the execution-safety requirement offline.
