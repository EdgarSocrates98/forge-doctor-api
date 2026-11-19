# Cycle 16.1 — Wave 13 report (forge-doctor-api)

Spec: `forjas/factory/specs/inbox/cycle16_1-wave13-forge-doctor-api.md`
Master prompt: `prompt_evo_forjas2.0.1.md` §13 ONDA 13, §7.2, §8, §9, §14.
Branch: `cycle16_1/wave13` — baseline `572e480` (main, clean).

## Scope verdict: CHANGED (not NO_CHANGE)

Real drift existed: the vendored install engine and context engine were
one canonical generation behind `the-forge` (cycle-16.1 frentes D+E).
Re-vendored via the normal flow (`vendor.py`), never hand-edited.

## What changed

1. **Re-vendored canonical installkit/context** —
   `the-forge/scripts/installkit/vendor.py forge-doctor-api --installkit-pkg src/forge_doctor_api`:
   - `scripts/forge_installkit.py` + `src/forge_doctor_api/_installkit.py`
     stamp `b574efcfbc13c63e` (was `dd279c639576d015`): receipt `counts`
     (§7.4 incremental accounting: `written`, `written_bytes`,
     per-action tallies), `InstallContext.mcp_command_resolved` +
     `_mcp_argv()`, `argv` recorded in `mcp[]` entries, `mcp_verify`
     probes the resolved argv.
   - `scripts/forge_context.py` + `src/forge_doctor_api/_forgecontext.py`
     stamp `ec2a7a80d2467000` (was `5674012d1a5760df`): `_forge_block_compact`
     — the compact L0 `forge:*` block for AGENTS.md (§8.1).
   - `vendor.py --check` after re-vendor: `rc=0`, no drift.

2. **Resolved MCP argv wired in both install paths** —
   `install/service.py::_ctx` and `scripts/forge_install.py::_ctx` now
   pass `mcp_command_resolved` (registered `cli.shim` →
   `sys.executable -m forge_doctor_api mcp`, mirroring the-forge's
   service wrapper); `mcp-verify` probes the resolved argv on both
   routes. §9.3: hosts never launch the MCP server through a PATH
   lookup.

3. **Receipts/status — `forge/InstallLifecycle/v1` compatible** —
   emitted vocabulary verified inside the closed sets:
   `status ∈ {planned, completed, failed}` (+ gate `refused`/`blocked`
   paths), `verification ∈ {PASS, FAIL, UNVERIFIED, BLOCKED}`,
   `checks ∈ CHECK_STATUSES`, health ∈ `{healthy, degraded, broken,
   unverified}`. A derived `lifecycle` block is optional per contract —
   the state is derivable from stored fields, so none is emitted
   (same as the canonical engine). Pinned by
   `test_receipt_vocabulary_is_lifecycle_compatible`.

4. **Incremental reinstall test** — engine seam
   (`test_reinstall_reports_zero_writes`,
   `test_reinstall_rewrites_only_drifted_assets`) and CLI end-to-end
   (`test_reinstall_is_incremental`): second apply reports
   `counts.written == 0`, `written_bytes == 0`, `.mcp.json`/`AGENTS.md`
   byte-identical, `status` healthy.

5. **Context metadata honest; minimal L0 boot** — `forge.json`,
   `forge.agentic.json` and both packaged mirrors verified
   byte-identical and version-consistent (0.3.4). Compact L0 block
   pinned by `test_agents_block_is_compact_l0`.

6. **Host surfaces sync verified** — `tests/test_forge_hosts.py` green
   (9 tests); `.claude/agents/README.md`, `.devin/` config present;
   host capability claims in docs corrected to observed surface.

7. **Docs updated (§14)** — README, `docs/installation/{mcp,
   portable-installation, global-installation, claude-code, codex-cli,
   devin-cli, copilot-cli, update-and-repair, troubleshooting}.md`:
   removed stale `forge-doctor-api:managed` marker references, stale
   host-skill-mirror claims and the "checkout-only lifecycle" claim;
   documented `counts`, absolute MCP argv, compact `forge:*` blocks.
   `CHANGELOG.md` wave-13 entry. Changed examples re-run for real.

## Gates

| Gate | Result |
|---|---|
| `pytest -q` | 2032 passed in 361.78s (final rerun, including shim-preservation regression) |
| `ruff check .` | clean |
| `mypy src` | clean |
| `python -m build` | wheel + sdist built |
| `forge-doctor-api lab` | all labs pass |
| `vendor.py --check` | rc=0 — zero drift vs canonical |
| bootstrap parity | sha256 `02f20671e2…` — identical to
`the-forge/scripts/installkit/forge_bootstrap.py` (gate green) |

## Live evidence (real install, `FORGE_HOME_OVERRIDE` sandbox)

- `install --yes` → `status: completed`; `.mcp.json` managed key =
  `{"command": "<abs>/.venv/bin/python", "args": ["-m","forge_doctor_api","mcp"]}`.
- `install --yes` (2nd) → `counts: {written: 0, written_bytes: 0}`,
  `mcp[0].action: "set"`; `.mcp.json`/`AGENTS.md` bytes identical.
- `doctor` → `healthy`; `mcp-handshake: PASS` over the resolved argv;
  `mcp-invoke: UNVERIFIED`; `forge-portal: NOT_APPLICABLE`.
- `repair` → `completed`; `uninstall --dry-run` → `planned` (no writes).
- Compact L0 block observed in AGENTS.md: name/version, `Domains:`,
  capability-manifest pointer, `AGENT_PROTOCOL.md` pointer — no
  CLI/MCP/discovery enumeration.

## Limitations and review status

- `counts` covers rendered assets only, not MCP, context documents or
  state writes. Zero counts on this forge's first install do not mean
  nothing was written. Byte comparisons cover content stability, not
  filesystem write telemetry or host token consumption.
- Registration now preserves the bootstrap's `cli.shim`, so a second
  install resolves the same argv; covered by a regression test.
- No independent reviewer tool is available in this worker. Independent
  review and CI must be handled by the parent/PR reviewer before merge.
- Optional `scripts/docs/check_docs.py` reports one pre-existing stale
  inventory error: `docs/cli.md:329` lists `obsidian status`, absent from
  `commands.generated.json`. The real parser accepts
  `python -m forge_doctor_api obsidian status --help` (exit 0). No
  unrelated inventory regeneration was included.
- API Forge/API Sentinel federated integration was not executed here;
  existing offline integration tests are covered by the full suite.

## Review notes for the independent reviewer

- Vendored files are byte-locked: verify stamps match
  `the-forge/scripts/installkit/` sha256-16, and that
  `src/_installkit.py` == `scripts/forge_installkit.py`,
  `src/_forgecontext.py` == `scripts/forge_context.py`.
- `.mcp.json` argv changed shape (`command` now absolute, `args`
  carries `["-m","forge_doctor_api","mcp"]` or the shim tail) — existing
  installs show `.mcp.json` drift until `repair` rewrites the key
  (documented in troubleshooting).
- No contract bump: `forge/InstallReceipt/v1` gains an additive
  `counts` field (schema already permits it); `forge/context/v1` is
  unchanged.
