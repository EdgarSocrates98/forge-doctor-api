# Development

## Layout

```text
src/forge_doctor_api/   the engine (see docs/architecture.md)
tests/                  pytest; pythonpath=src
labs/                   Forge Lab corpus + expected.yaml ground truth
factory/                Loop Factory: specs/{inbox,active,archive},
                        prompts/, reviews/, runs/, quality-gate.md
.github/workflows/      doctor-scan.yml
```

## Daily commands

```bash
python -m pytest -q                 # full suite
python -m pytest -q tests/test_x.py # focused
python -m ruff check . --fix        # lint (+autofix)
python -m mypy src                  # strict typecheck
python -m build                     # wheel + sdist
forge-doctor-api lab                # corpus precision/recall
```

## Clean-install reproduction (CI equivalence)

The dev environment drifts (stale editable installs, pre-installed
extras). Reproduce the CI contract in a throwaway venv:

```bash
# minimal install — core only, extras absent
python -m venv .venv-ci-min
.venv-ci-min/Scripts/activate            # .venv-ci-min/bin/activate on POSIX
python -m pip install -e . pytest ruff mypy types-PyYAML build
python -m pytest -q                      # optional-extra tests skip-with-reason
python -m ruff check . && python -m mypy src && python -m build

# full install — every advertised extra
python -m venv .venv-ci-full
.venv-ci-full/Scripts/activate
python -m pip install -e ".[graphql,mcp]" pytest ruff mypy types-PyYAML build
python -m pytest -q                      # GraphQL + MCP tests active
forge-doctor-api lab                     # full corpus incl. graphql/*
```

Rule: a test must never depend on whether the *developer's* env happens
to have an extra installed. Optional-capability tests declare
`pytest.importorskip`, and lab scenarios declare `requires_extras` in
`expected.yaml` — absence is a recorded skip, never a failure and never
a silent pass.

## Conventions that are enforced

- **Frozen dataclass models** deriving from `core.models.Model` —
  `to_dict()` is the serialization boundary.
- **Determinism** — sort before emitting; no `set` iteration into
  output; no wall-clock reads (inject via `ProjectContext` clock).
- **Every finding carries evidence.** A `Finding` with
  `Confidence.UNKNOWN` must list `unknowns`; `ModelError` is raised
  otherwise.
- **Entity ids** are `kind:domain:identifier` — kind is snake_case,
  domain is lowercase `[a-z0-9_.-]`, identifier is free-form printable.
  Put file paths in the *identifier* (`kind:domain:path#pointer`), never
  in the domain.
- **Redaction** is always on — extend `core/redaction.py` patterns when
  a new secret shape appears.
- **Check ids** match `{NAMESPACE}{3-4 digits}`; add specs to the
  family `catalog.py`, not inline strings.
- **No new runtime dependencies** without strong justification —
  current set is `typer`, `rich`, `pyyaml` (+ optional `graphql-core`).

## Adding a check

1. Add a spec to the family catalog (`checks/<family>/catalog.py`) with
   severity, confidence, evidence kind, description.
2. Emit `Finding`s in the family engine — anchored to `SourceLocation`,
   evidence-bearing, with `UnknownFact`s for anything unresolvable.
3. Add/extend lab fixtures if the check is observable on a corpus
   project (`labs/<domain>/...` + `expected.yaml`).
4. Tests in `tests/test_<family>.py`; keep them hermetic (no network,
   tmp_path fixtures, deterministic ordering assertions).

## Loop Factory lifecycle

Specs in `factory/specs/inbox/` are moved to `active/` only when
implementation starts (`loop-factory dispatch --stage`). After
verification, generate review evidence (`loop-factory review <id>`),
record the verdict, then `loop-factory archive <id> --accepted` — never
archive before review evidence exists. Run metadata and records stay
under `factory/runs/`; quality-gate checklist in
`factory/quality-gate.md`.
