# Themes and visual identity

The kit uses semantic roles, not raw colors:

| Role | ANSI | Used for |
|---|---|---|
| primary | bold | titles, section heads |
| accent | cyan | section labels |
| muted | dim | hints, separators, paths |
| ok | green | PASS/HEALTHY/completed states |
| fail | red | FAIL/DEGRADED/blocked states |
| warn | yellow | UNVERIFIED/pending states |

With `NO_COLOR` or a dumb terminal every role degrades to plain text —
the information is in the words, not the paint.

Per-forge identity is carried by the forge name in headers and its own
menu/domain terminology; the underlying interaction model (selection,
multi-select, confirm, dashboard) is identical across all seven forges.
