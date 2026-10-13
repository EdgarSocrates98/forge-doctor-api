You are implementing Loop Factory spec `010-api-versioning`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\010-api-versioning.md`
        Spec hash: `07303c73f0f979f5d49db4810095291eb58133517ddb8379f451f2b8b8017eaf`

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

- Owner: project owner; decisions sourced from §7.4, §18, §19.
- Problem: version and lifecycle awareness feed retirement-safety and drift questions (§0).
- Out of scope: GraphQL schema-evolution tracking (012), protobuf package versioning (013), deprecation *readiness scoring* (spec 025 consumes this model).
- Review failure: version "detected" from naming guesses, lifecycle asserted without evidence.
- Riskiest assumption: version signals are heterogeneous — mitigate by recording detection source and UNKNOWN when no signal exists.
- Smallest acceptable: `ApiVersionModel` + detection of URI/header/media-type versioning + lifecycle fields.
- RESOLVED: first pass ignores GraphQL/proto version signals — deferred to specs 012/013 as scoped. Detection mechanisms are URI, header, media-type only.

# Context

`ApiVersionModel` (§18) detects URI versioning, header versioning, media-type versioning (GraphQL schema evolution and protobuf package/version deferred to their specs). Deprecation model (§19): `deprecated`, `deprecation_date`, `sunset_date`, `replacement`, `clients_remaining`, `traffic_remaining`. Lifecycle states per §7.4: EXPERIMENTAL, ACTIVE, DEPRECATED, SUNSET, RETIRED, UNKNOWN.

# Acceptance Criteria

- `ApiVersionModel`: version identifier, detection mechanism (`uri | header | media_type`), source evidence, lifecycle state.
- Detect URI version segments (`/v1/`, `/v2/`) and header/media-type version signals from OpenAPI servers/paths/parameters.
- Deprecation fields populated from explicit contract metadata (`deprecated`, `x-deprecation*`, `sunset` headers/extensions); `clients_remaining`/`traffic_remaining` only from runtime evidence — absent → UNKNOWN, never inferred.
- Lifecycle classification per §7.4 with evidence for each assignment.
- Tests per §202: positive/negative/malformed/determinism; version-free APIs classified UNKNOWN.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- No version inference from naming conventions alone (e.g. "new" in titles).
- Evidence-based lifecycle only — don't synthesize dates.

# Review Notes

- Check media-type versioning (`application/vnd.x.v2+json`) parsing edge cases.
- Confirm UNKNOWN lifecycle doesn't masquerade as ACTIVE.
