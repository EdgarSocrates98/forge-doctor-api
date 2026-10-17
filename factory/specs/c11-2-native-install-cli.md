---
id: c11-2-native-install-cli
title: Native install lifecycle via wheel-carried public CLI (P2-002, RC exception)
agent: devin
risk: medium
grill: delegated-to-owner-pr-review
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m build
---

# RC Exception Record

This spec is the `factory/specs/` deviation entry `docs/rc-discipline.md`
requires before a public-surface change merges during the RC window. The
change is owner-requested (cycle 11.2, ticket P2-002); the PR carries the
approval. ADR-0006 records the architecture decision.

- What changes: new public CLI group `forge-doctor-api install`
  (verbs `status|doctor|repair|uninstall|update|mcp-verify`, bare verb
  applies). EXPERIMENTAL stability — `cli/catalog.py` + `docs/cli.md`.
- What does not change: contract schemas (receipts stay
  `forge/InstallReceipt/v1`, `forge/InstallationHealth/v1`,
  `forge/InstallationManifest/v1`), version `0.2.0`, runtime deps
  (stdlib only), MCP tool inventory, check ids, engine purity.
- Boundary: `tests/test_boundary.py` gains `_INSTALL_SURFACE` —
  `_installkit.py`, `install/*`, `cli/install_cmd.py` own the only
  `os`/`subprocess` surface in `src/`; `test_install_surface_isolation`
  proves the scan/engine path never imports them.
- Vendored parity: `src/forge_doctor_api/_installkit.py` is byte-identical
  to `scripts/forge_installkit.py` — guarded by
  `test_package_carries_install_surface`.
- Checkout adapter: `scripts/forge_install.py` unchanged and still the
  bare-tree entrypoint.
- Delegation argv for the forge-cli catalog (forge-cli is NOT touched in
  this PR): `{python} -m forge_doctor_api install [--yes|update|uninstall]`.
- Regenerated artifacts: `docs/rc-baseline.json` (cli_command_count
  28 → 34), `docs/reference/commands.generated.json` — produced by the
  committed generators, not hand-edited.

# Acceptance Criteria

- `forge-doctor-api install --root T --yes` applies; `status`/`doctor`
  report healthy; `uninstall` removes ledger-owned assets only;
  `update --to latest` refuses; `mcp-verify` emits the health doc.
- `python -m forge_doctor_api install ...` works (the catalog argv).
- `test_install_cli.py` covers the wheel path in-process + via `python -m`.
- All RC gates green; boundary/isolation tests prove the engine stays pure.
