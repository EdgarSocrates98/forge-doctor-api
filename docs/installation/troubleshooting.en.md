# Troubleshooting — Forge Doctor API (EN)

| Symptom | Action |
|---|---|
| `command not found: forge-doctor-api` | run `./setup.sh` again; open a **new** terminal (launcher lands on PATH) |
| `FORGE-INSTALL-LOCKED` | another install is running or was interrupted; the lock expires and is recovered automatically — retry |
| `FORGE-INSTALL-PLAN-NOT-APPROVED` | mutations require `--yes` after reviewing `--dry-run` |
| `FORGE-INSTALL-NOT-A-REPO` | project scope needs a `.git` root or `--root` |
| `FORGE-INSTALL-DRIFT` | managed files changed on disk — run `repair` to heal managed regions, keep your edits |
| `FORGE-INSTALL-OWNERSHIP` | files managed by another forge/profile — no silent overwrite; use `--force` only deliberately |
| MCP `FAIL` + `stderr_tail` | missing dependency (e.g. the `mcp` extra) — install it and re-run `mcp-verify` |
| stale/partial install | `uninstall` removes only ledger-owned files; `status`/`doctor` show the truth |

Português: [troubleshooting.md](troubleshooting.md).
