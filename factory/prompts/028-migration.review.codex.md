Review Loop Factory spec `028-migration` against current working tree.

        Native adapter: `codex`
        Spec path: `factory\specs\active\028-migration.md`

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

- Owner: project owner; decisions sourced from §77–§83, §167.
- Problem: answer "which migration preserves API semantics?" — REST→gRPC, REST→GraphQL, sync→async, gateway→gateway, v1→v2.
- Out of scope: executing migrations, generating target artifacts — analysis/classification only.
- Review failure: REST→GraphQL presented as direct endpoint→field mapping (§80 forbids), semantics losses unreported.
- Riskiest assumption: comparison dimension coverage — RESOLVED: coverage = the explicit §79 (REST→gRPC) and §81 (sync→async) checklists, all dimensions mandatory; a clean verdict without full dimension coverage is a bug.
- Smallest acceptable: `ApiMigrationIntelligence` + §78 classes + REST→gRPC and sync→async comparisons + contract-version diff + SDK-impact signal.

# Context

`ApiMigrationIntelligence` (§77) covers REST→gRPC, REST→GraphQL, gateway→gateway (AWS API Gateway → Kong/Azure APIM), sync→async, v1→v2. Classification (§78): DIRECT, APPROXIMATE, REDESIGN_REQUIRED, NO_EQUIVALENT, UNKNOWN. REST→gRPC compares request/response, status semantics, streaming, metadata/headers, error model, timeouts, idempotency (§79). REST→GraphQL is normally REDESIGN_REQUIRED — no automatic endpoint→field mapping (§80). Sync→async compares request-response, delivery semantics, correlation, retry, DLQ, ordering, event schema (§81). Contract migration compares OpenAPI versions (§82). Client-generation impact detects whether contract changes affect SDK generation (§83).

# Acceptance Criteria

- `ApiMigrationIntelligence` evaluating the §77 use cases over existing models; output per operation/element = classification + preserved semantics + lost/changed semantics + unknowns.
- §78 classes: DIRECT, APPROXIMATE, REDESIGN_REQUIRED, NO_EQUIVALENT, UNKNOWN.
- REST→gRPC comparison across all §79 dimensions; sync→async across all §81 dimensions.
- REST→GraphQL defaults to REDESIGN_REQUIRED unless element-level equivalence is demonstrable — never auto-maps endpoints to fields (§80).
- Contract-version migration (§82): OpenAPI 3.0→3.1→3.2 semantic diff using spec 008 machinery.
- Client-generation impact signal (§83): flags contract changes that alter SDK surface.
- Feeds §167 decision questions ("can this move to gRPC", "can this become async") with facts/constraints/tradeoffs/unknowns — no subjective verdict.
- Tests per §202 incl. non-mappable cases → NO_EQUIVALENT/UNKNOWN.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Analysis only — never generates target contracts or migration code.
- Semantics-loss reporting is mandatory; a "clean" verdict without dimension coverage is a bug.
- UNKNOWN over optimistic classification.

# Review Notes

- Verify streaming/idempotency semantics are compared, not just shapes (§79).
- Confirm REDESIGN_REQUIRED outputs explain *why* in dimension terms.
