# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | yes       |

The project is pre-1.0. Only the latest release line receives fixes.

## Reporting a vulnerability

Do **not** open a public issue for a suspected vulnerability.
Report privately to the maintainer via GitHub private vulnerability
reporting, or email the address listed on the repository owner's
profile.

Please include: affected version, reproduction steps or fixture, and
the impact you believe is possible. Expect an acknowledgement within
7 days.

## Scope notes

`forge-doctor-api` is a deterministic, offline-first analyzer. Its
threat model centers on:

- **crafted input files** (contracts, runtime exports, IaC, configs)
  causing crashes, excessive memory, or path escapes — parsers must
  never execute target code;
- **output integrity** — findings must be evidence-backed; a bug that
  fabricates or hides findings is a security-relevant defect;
- **dependency hygiene** — runtime deps are limited to typer, rich,
  pyyaml (+ optional graphql-core); report dependency advisories.

Bugs in the analysis quality itself (false positives/negatives) are
regular issues unless they enable the above.
