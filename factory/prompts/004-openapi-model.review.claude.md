Review Loop Factory spec `004-openapi-model` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\004-openapi-model.md`

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

- Owner: project owner; decisions sourced from §10, §128, §129, §142, §181, §182, §202.
- Problem: OpenAPI is the first-class contract front (§142) — the whole v0.1 demo chain depends on parsing it correctly (§225 Phase D).
- Out of scope: OAS### checks (spec 005), drift/breaking engines (007/008), AsyncAPI/GraphQL/gRPC.
- Review failure: crash on circular $refs, silent remote fetch, accepting non-OpenAPI YAML as OpenAPI, nondeterministic model output.
- Riskiest assumption: $ref resolution across files + cycles is correct — mitigate with explicit cycle detection and adversarial fixtures (§100, §202).
- Smallest acceptable: OpenAPI 3.0/3.1/3.2 YAML+JSON → `OpenApiProjectModel`, local/relative/cross-file $refs, cycles handled, external refs recorded unresolved.

# Context

Phase D (§225). OpenAPI must be proven first (§142). `OpenApiProjectModel` covers §10.1: documents, servers, paths, operations, parameters, request_bodies, responses, schemas, callbacks, webhooks, security_schemes, security_requirements, tags, external_docs, extensions. Support 3.0.x / 3.1.x / 3.2.x (§10); knowledge of the family comes from bundled knowledge packs, never live fetch (§128–§129). Operation identity: `operationId` preferred, fallback `method + normalized path` (§181); path normalization is conservative — structurally similar paths are NOT merged blindly (§182).

# Acceptance Criteria

- Parser accepts OpenAPI 3.0.x/3.1.x/3.2.x in YAML and JSON; invalid/unsupported versions produce a structured result, not a crash (feeds OAS001 later).
- `OpenApiProjectModel` exposes all §10.1 fields with source locations preserved.
- $ref resolution: local refs, relative refs, cross-file refs resolved; remote URL refs recorded as `UnresolvedExternalRef` — never fetched (§10.2, §129).
- Reference cycles detected and handled without recursion crash; cycle locations recorded (§10.3).
- Operation identity helper: `operationId` → fallback `method + normalized path`; normalization rules documented and conservative (§181–§182).
- Detection gate: a YAML is only treated as OpenAPI with strong markers (e.g. `openapi:` version field) — `paths:` alone is insufficient (§101).
- Tests per §202: positive/negative/malformed/adversarial/cross-file/dynamic-unknown/serialization/determinism. Include §100-style adversarial fixtures: random YAML named `openapi.yml`, JSON with `paths` but no OpenAPI markers, malformed spec, recursive refs.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- No remote fetching — external URL refs are recorded, never resolved (§10.2).
- Adding `pyyaml` (or equivalent) is expected and justified here; keep it the only new runtime dep.
- Deterministic model output: same input → identical serialized model.
- No checks/findings emission in this spec — model only.

# Review Notes

- Attacks to verify: deep $ref cycles, self-referencing schemas, mixed 3.0/3.1 constructs, spec-without-openapi-key.
- Confirm model keeps extensions (`x-*`) rather than dropping them — later specs consume them.
