# Installation wizard

Bare `forge-doctor-api install` on a TTY opens the guided wizard. On a non-TTY it
exits with a usage error pointing at `install apply` — scripts keep the
flag contract.

## Steps

1. **Environment check** — real evidence: Python version, git, host
   binaries on PATH.
2. **Scope** — `project` / `workspace` / `user`.
3. **Profile** — Balanced (recommended), Economy (minimal), Full.
4. **Optional components** — multi-select with profile defaults:
   `skills`, `agents`, `mcp`, `tui`, `graph-studio`. Unchecked components
   are persisted to `components.json`; declining `graph-studio` makes
   `graph ui` refuse with an unlock hint.
5. **Hosts** — multi-select over detected AI hosts.
6. **Review** — the real dry-run plan (managed writes count + paths).
7. **Confirm** — explicit approval; Esc cancels with zero writes.
8. **Apply** — the governed install runs (`--yes` equivalent, with
   locking, ledger, rollback on failure).
9. **Verify** — `install doctor` health report.

Non-interactive equivalent:

```bash
python scripts/forge_install.py install --scope project --profile recommended --host all --dry-run
python scripts/forge_install.py install --scope project --profile recommended --host all --yes
# optional components:
python scripts/forge_install.py install --yes --components skills,mcp,tui,graph-studio
python scripts/forge_install.py doctor
```

## States shown

The wizard and dashboards distinguish honestly:

- `INSTALLED` — ledger records the install (not proof of health).
- `CONFIGURED` — CLI probe passes.
- `READY`/`HEALTHY` — verification checks pass.
- `RESTART_REQUIRED` — host assets written; the host reads them next
  session (never claimed as ACTIVE).
- `UNVERIFIED` — no evidence either way.
