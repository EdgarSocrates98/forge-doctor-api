# ADR-0006 — Native install lifecycle as a wheel-carried public CLI

- Status: accepted (RC exception — cyc11.2 P2-002, owner-requested)
- Date: 2026-10-17

## Context

The `forge/*` installation contract v1 was implemented only as the
checkout-level adapter `scripts/forge_install.py` +
`scripts/forge_installkit.py`. A wheel consumer had no installer:
`forge-cli --native` (registry method) could not delegate and had to
report an honest SKIP ("instalador por script do repositório —
indisponível no método registry"). The gap is registered as cycle 11.2
P2-002.

Three options were on the table:

- **A — ship the script as wheel data + entry point.** A console script
  cannot target a data file; a launcher would have to `subprocess` or
  `runpy` the bundled script — the same banned-import problem inside
  `src/`, plus an extra indirection layer to test.
- **B — public CLI subcommand backed by wheel-carried code.**
  `forge-doctor-api install` (Typer sub-app) over
  `forge_doctor_api.install.service` + the vendored
  `forge_doctor_api._installkit`. This is exactly the layout the sibling
  `forge-doctor-data` already ships, and the installkit header names
  `<pkg>/_installkit.py` as a primary vendoring target.
- **C — keep the installer source-only.** Preserves the narrowest
  boundary but leaves `forge-cli --native` permanently SKIPPED — the
  motivating defect.

The installer is stdlib-only, deterministic, and bounded (sha256 ledger,
owned writes only, no network) — B was chosen.

## Decision

- The installkit is vendored **byte-identical** as
  `src/forge_doctor_api/_installkit.py` — drift is impossible to hide
  (`test_package_carries_install_surface` asserts byte-parity with
  `scripts/forge_installkit.py`; `_SOURCE_SHA256` stays intact).
- `src/forge_doctor_api/install/service.py` carries the `ForgeSpec` and
  the typed verb wrappers — byte-equivalent behavior to
  `scripts/forge_install.py` (same verbs, same receipts, same ledger).
- `src/forge_doctor_api/cli/install_cmd.py` exposes the lifecycle under
  `forge-doctor-api install` (bare verb applies; `status`/`doctor`/
  `repair`/`uninstall`/`update`/`mcp-verify` subcommands).
- The boundary test (`tests/test_boundary.py`) gains an explicit
  `_INSTALL_SURFACE` allowlist — the four install modules own the only
  `os`/`subprocess` surface in `src/`; `test_install_surface_isolation`
  proves the scan/engine path never imports them. The offline guarantee
  is unchanged: subprocess is confined to `kit._spawn` and
  `service.update` (pinned `pip install --upgrade`, no shell, 900s cap).
- `scripts/forge_install.py` remains the checkout-level adapter for
  bare-tree installs before a wheel exists — unchanged.

### Delegation argv (for the forge-cli catalog)

`forge-cli` does not change in this PR; the catalog template it should
adopt for `forge-doctor-api` is:

```text
install:   {python} -m forge_doctor_api install --yes
update:    {python} -m forge_doctor_api install update
uninstall: {python} -m forge_doctor_api install uninstall
```

(`{bin}`-form `forge-doctor-api install ...` is equivalent once the
console script is on PATH; the `{python} -m` form needs no PATH
assumption and is what tests exercise.)

## Consequences

- `forge-cli --native` can delegate install/update/uninstall to the
  published wheel instead of reporting SKIP.
- Public-surface change during the RC window: recorded here, in
  `factory/specs/c11-2-native-install-cli.md`, and in the PR — the
  exception path `docs/rc-discipline.md` requires.
- `docs/rc-baseline.json` `cli_command_count` moves 28 → 34 and the new
  command paths are registered EXPERIMENTAL in
  `cli/catalog.py`/`docs/cli.md`; `forge.json` `install_command` now
  points at the module argv.
- New module count in `src/` grows by four files, all leaf — no engine
  module gains an import.

## Alternatives

- Wheel-data script (A): rejected — extra launcher indirection for the
  same boundary exception, and the script would still fork from the
  vendored engine.
- Source-only (C): rejected — keeps the defect.
