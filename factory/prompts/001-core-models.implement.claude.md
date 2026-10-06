You are implementing Loop Factory spec `001-core-models`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\001-core-models.md`
        Spec hash: `058e32d8f80cfd5720f46a2e8f8c3e52cae980e3533d4c0d5271e2b6ebc01288`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from `prompt_evo_inicial.md` §3, §5, §209, §217.
- Problem: bootstrap the deterministic API evidence/diagnosis engine (Forge Doctor API) — sibling of Forge Doctor Data (§0, §4).
- Out of scope: any domain analyzer, OpenAPI parsing, checks, runtime ingestion. Skeleton + core models only (§225 Phase A).
- Review failure: missing directory layout per §217, missing core model types per §5, non-clean ruff/mypy, runtime deps beyond Typer/Rich.
- Riskiest assumption: core model shapes will remain compatible with future Forge shared contracts — mitigate by designing per §5/§212 but NOT extracting a shared package (§213).
- Smallest acceptable: installable package, directory layout, core model types with deterministic serialization, Typer CLI stub, pytest suite, ruff+mypy clean.

# Context

Forge Doctor API is a deterministic, offline-first, evidence-first engine for API architecture intelligence (§0–§1). This spec creates the repository foundation (Phase A of §225): package skeleton per §217, core universal models per §5, and the CLI entry point. Stack is fixed by §3: Python >= 3.11, Poetry, Typer, Rich, pytest, Ruff, mypy. Version starts at 0.1.0 — never call it 1.0 early (§209).

# Acceptance Criteria

- `pyproject.toml` (Poetry) declares `forge-doctor-api` version `0.1.0`, `requires-python >=3.11`, runtime deps limited to `typer` and `rich`, dev deps `pytest`, `ruff`, `mypy`.
- Package layout under `src/forge_doctor_api/` matches §217: `analyzers/`, `checks/`, `core/`, `cli/`, `integrations/`, `output/`, `plugins/`, `sdk.py`.
- `core/models.py` defines the universal concepts from §5: `Evidence`, `Finding`, `Confidence`, `Severity`, `Entity`, `Relationship`, `Capability`, `CapabilityDependency`, `RuntimeEvidence`, `ChangeEvent`, `Baseline`, `Regression`, `SLO`, `Remediation`, `Experiment`, `UnknownFact`, `DecisionContext`.
- `core/context.py` defines `ProjectContext` — all host-sensitive access (filesystem roots, workspace paths) goes through it, per hermetic execution (§203).
- CLI entry point `forge-doctor-api` (Typer) exposes at least a `scan`/`inventory` placeholder command group structure matching §159–§166 naming, each printing "not implemented" or equivalent.
- Models serialize deterministically (stable key order, no datetime.now() leakage unless injected).
- Tests cover model construction, serialization round-trip, and determinism (two serializations byte-identical), per the test contract in §202 (positive/negative/malformed/determinism where applicable).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` all pass.

# Constraints

- Deterministic, offline-first, no network calls, no LLM dependency (§1).
- Prefer stdlib; keep dependencies small (§3). No parser libs yet (YAML/GraphQL/proto arrive with their specs).
- Do not implement domain logic (no OpenAPI/routes/checks) — later specs own that.
- Do not extract or reference a shared Forge contracts package (§211–§214).
- No comments beyond what the codebase style needs; no speculative abstractions.

# Review Notes

- Verify `ProjectContext` is the only path to host resources (§203) — later hermetic tests depend on it.
- Confidence/Severity/UNKNOWN semantics must match Forge Doctor Data conventions conceptually (§2: shared = how intelligence is represented).
- Check serialization determinism explicitly — dict ordering and set iteration are the usual leaks.
