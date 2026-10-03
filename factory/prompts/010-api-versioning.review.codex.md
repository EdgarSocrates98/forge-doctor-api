Review Loop Factory spec `010-api-versioning` against current working tree.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\010-api-versioning.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

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
