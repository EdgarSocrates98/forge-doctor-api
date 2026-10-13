# Agent instructions — forge-doctor-api

Deterministic, offline-first, evidence-first API intelligence engine.
Read `docs/architecture.md` before making structural changes.

## Commands

```bash
python -m pytest -q          # tests (sockets are hard-blocked)
python -m ruff check .       # lint, line length 100
python -m mypy src           # strict
python -m build              # wheel + sdist
forge-doctor-api lab         # corpus precision/recall (expected: all pass)
```

## Hard rules

- Deterministic only — no LLM calls, no wall-clock in the engine
  (inject via `ProjectContext`), sort all emitted collections.
- No network imports in `src/` (socket/urllib/http/requests/httpx/
  subprocess). All file I/O via `ProjectContext`.
- No raw schema payloads or raw spans in stored/exported data.
- Findings require evidence; `Confidence.UNKNOWN` requires `unknowns`.
- Entity ids: `kind:domain:identifier`; file paths go in the
  identifier, not the domain.
- Do not add runtime dependencies beyond typer/rich/pyyaml (+graphql extra).
- Keep `docs/assets/logo.png` and its README display intact.
- Version is `0.2.0` — do not bump without an owner-documented
  rationale in `docs/versioning.md`, do not publish, do not commit to
  a 1.0 API.
- RC window: `docs/rc-discipline.md` binds what may and may not
  change — public-surface/contract/dependency changes are forbidden
  without a recorded exception.

## Loop Factory

- `factory/specs/inbox → active` via `loop-factory dispatch --stage`
  (binary lives in `../Loop-Factory/bin/loop-factory`).
- Review before `loop-factory archive <id> --accepted`; run records in
  `factory/runs/`, checklist in `factory/quality-gate.md`.
