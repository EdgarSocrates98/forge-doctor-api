# Contributing

Read `AGENTS.md` first — it carries the hard rules (determinism,
offline-first, evidence-first, no network imports in `src/`, no raw
payloads in outputs) and the verification commands.

## Setup

```bash
pip install -e . pytest ruff mypy types-PyYAML build
```

## Verify before submitting

```bash
python -m pytest -q          # tests (sockets are hard-blocked)
python -m ruff check .       # lint
python -m mypy src           # strict types
python -m build              # wheel + sdist
forge-doctor-api lab --no-record   # corpus precision/recall
```

All of the above also run in `.github/workflows/quality.yml` on every
push to `main` and every pull request, on Python 3.11–3.13.

## Specs

Product changes flow through Loop Factory specs in `factory/specs/`
(inbox → active → archive). A spec is the source of truth: implement
its acceptance criteria, run its `verification:` block, and record the
result in `factory/runs/`.
