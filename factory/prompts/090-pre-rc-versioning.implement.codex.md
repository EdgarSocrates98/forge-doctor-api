You are implementing Loop Factory spec `090-pre-rc-versioning`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\090-pre-rc-versioning.md`
        Spec hash: `ce59314cbf0468606dea84e7f941950d268e598bd2858c3d61a9644ce972a254`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

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

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 10 and items §17/§24/§26/§30.
- Problem: the owner records that `0.1.x` undersells the shipped
  surface — the prompt recommends `0.2.0` to mark the "Trusted
  Unified Doctor" phase, conditioned on documented rationale. The
  standing AGENTS.md rule pins `0.1.0` to prevent *unauthorized*
  bumps; this spec executes an *authorized, documented* bump and
  updates the rule text to the new pinned value. Separately:
  docs-as-contract coverage and the readiness scorecard are
  incomplete.
- Out of scope: `1.0` (explicitly forbidden — no stability promise
  committed), publishing, tagging (release stays workflow-gated).
- Review failure: a version bump without the rationale the prompt
  conditioned it on; scorecard claims without a linked proof
  artifact; docs-as-contract covering only `--help` output.
- Riskiest assumption: bumping desyncs surfaces — RESOLVED: the
  spec-089 version gate test catches pyproject/__version__/
  SDK_VERSION/wheel/manifest divergence; this spec updates all five.
- Smallest acceptable: `docs/versioning.md` with the decision +
  rationale + triggers; bump executed across all version sites with
  AGENTS.md rule text updated to the new pin; docs-as-contract
  tests for README/release/MCP/contract examples; readiness
  scorecard doc; test-pyramid doc section.

# Context

Phase 10. Existing: `docs/release-policy.md` (semver rules,
surface list), `test_docs_contract.py` (docs↔CLI drift),
`output-contract.md` v1, `fleet/report.py` portfolio facts.
Missing: version decision record, expanded docs-as-contract,
readiness scorecard, test-pyramid documentation.

# Acceptance Criteria

- `docs/versioning.md`: why version communicates trust stage;
  what MINOR/RC/1.0 each mean for this project; the recorded
  decision (bump to `0.2.0` per owner prompt — "Trusted Unified
  Doctor" phase marker, wire contract + boundary proven, no 1.0
  commitment); triggers that would justify `1.0` later.
- Version bump executed: `pyproject.toml` `version`,
  `__init__.py` `__version__`, `sdk.py` `SDK_VERSION` all move to
  `0.2.0`; AGENTS.md version line updated to the new pin (rule
  spirit preserved: no bump *without owner-documented rationale*);
  CHANGELOG gains the wave entry; `docs/rc-baseline.json`
  regenerated.
- Docs-as-contract expansion: golden/drift tests asserting
  (a) every README command exists in the CLI catalog, (b) release
  docs' reproduction commands are runnable forms, (c) MCP doc tool
  names match the frozen inventory, (d) contract doc examples
  parse through `contracts.models`.
- `docs/release-readiness.md` scorecard: one row per RC claim
  (install matrix, contract conformance, MCP boundary, plugin
  boundary, corpus depth, scale envelope, compat precision,
  sec/rel precision, release artifacts, boundary purity) with
  columns claim / proof artifact / gate — every row links a real
  file or test.
- `docs/testing.md` (new or section): test pyramid — unit /
  adversarial / conformance / boundary / corpus / scale / smoke —
  with which layer owns which risk and why counts per layer.
- API portfolio facts: `fleet/report.py` (or its doc) records the
  measured per-repo fact set — no scores, no invented health
  metrics; doc updated.
- pytest/ruff/mypy pass; version gate test from spec 089 stays
  green.

# Constraints

- The bump is authorized only because the owner prompt recommends
  it *with rationale* — `docs/versioning.md` is that rationale and
  must exist in the same commit.
- No 1.0, no publish, no tag.
- README/logo and every doc's displayed commands stay true.
