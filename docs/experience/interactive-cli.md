# Interactive CLI

Bare `forge-doctor-api` on a real terminal opens the interactive home — a menu
whose entries run this forge's **real** commands. Nothing decorative:
every option executes the canonical CLI surface or the governed install
service.

```bash
forge-doctor-api            # interactive home (TTY)
forge-doctor-api --help     # full command surface
```

On a non-TTY (CI, pipes, SSH without terminal) bare `forge-doctor-api` prints the
product summary instead — automation never hits an interactive prompt.

## Keyboard model

| Key | Action |
|---|---|
| ↑ / ↓ | move selection |
| Enter | confirm |
| Space | toggle (multi-select) |
| q / Esc | cancel or quit |
| Ctrl+C | cancel immediately |

## What the menu runs

The menu also offers **Graph Studio** — it runs the real `graph ui`
argv (embedded local explorer on 127.0.0.1). If `graph-studio` was
declined at install, the underlying command refuses with a named code;
the menu shows that exit verbatim.

Menu entries resolve the CLI argv — the installed launcher when present,
otherwise the checkout entry point declared in `forge.agentic.json` —
and execute it as a real subprocess. The exit code is shown verbatim.

## The Forge Command Center (the-forge only)

`theforge` home additionally shows the real specialist lifecycle
(`specialists collect`), detected AI hosts (evidence-based), and recent
delegations from `.forge/delegations/` — the same data the `specialists`,
`hosts` and `task` commands report.
