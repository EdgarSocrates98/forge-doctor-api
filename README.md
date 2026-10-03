<p align="center">
  <img src="docs/assets/logo.png" alt="Forge Doctor API" width="440">
</p>

# Forge Doctor API

Deterministic, offline-first, evidence-first engine for API architecture intelligence.

Status: `0.1.0` — deterministic scan, diff, diagnose, inventory, lab, and
handoff surface. Not yet a stable public API.

```text
poetry install
poetry run forge-doctor-api --help
poetry run pytest -q
```

## Scan & CI gate

```text
forge-doctor-api scan TARGET \
  --fail-on breaking,security,policy \
  --baseline PATH --policy PATH \
  --format console|json|jsonl|sarif|agent --out FILE
```

Exit codes: `0` pass, `1` gate failure, `2` usage error. The
`breaking` category requires `--baseline`; `security` blocks only on
HIGH-confidence findings; UNKNOWN-confidence findings never block.
`.github/workflows/doctor-scan.yml` wires the same command into CI.
