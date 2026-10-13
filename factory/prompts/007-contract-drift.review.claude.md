Review Loop Factory spec `007-contract-drift` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\007-contract-drift.md`

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

- Owner: project owner; decisions sourced from §14, §15, §143, §144, §145, §146, §181, §182.
- Problem: detect where declared contracts and real implementation diverge (§225 Phase G).
- Out of scope: breaking-change classification of two contract versions (spec 008), runtime drift (019).
- Review failure: engine picks a source of truth on its own, fuzzy route↔operation matching, missing DRIFT ids, silent unmatched items.
- Riskiest assumption: operation↔route identity matching is correct — mitigate with §181 identity rules + conservative path normalization §182.
- Smallest acceptable: OpenAPI model vs RouteModel comparison emitting DRIFT001–010 with authority policy honored.

# Context

Phase G (§225). `ApiContractDrift` compares OpenAPI vs source routes (§14). The system must support both contract-first and code-first repos and must NOT assume which is authoritative (§143): `contract_authority` config = `openapi | implementation | gateway | none` (§144); when undeclared, report conflict — never decide alone (§145). `ApiErrorModel` (§146) is included here: compare HTTP status + error body shapes between contract and implementation (org standard error contract support lands with policies, spec 023).

# Acceptance Criteria

- Matching engine pairs OpenAPI operations with discovered routes using §181 identity: `operationId` where correlatable (e.g. FastAPI operation_id / handler name), else `method + normalized path`; normalization conservative per §182 (`/users/{id}` vs `/users/{userId}` equivalent only when semantics unknown-safe — record, don't blind-merge).
- Findings DRIFT001–010 per §14: documented operation missing implementation; implemented route absent from contract; method mismatch; parameter mismatch; request schema mismatch; response schema mismatch; status-code drift; auth drift; deprecated contract still implemented; undocumented breaking implementation.
- `contract_authority` config consumed: under `openapi`, undocumented routes are flagged differently than under `implementation`; under `none`/undeclared, both directions reported as conflict without asserted verdict (§144–§145).
- Contract graph edges per §15: API–EXPOSES→Operation, Operation–ACCEPTS→Schema, Operation–RETURNS→Schema materialized in ServiceGraph.
- `ApiErrorModel` comparison: status codes + error body schema drift between contract and implementation (§146).
- Every finding carries evidence_kind (`STATIC`/`CONFIG`/`OBSERVED_METADATA` as applicable), both sides' source_location.
- Tests per §202: positive/negative/malformed/adversarial/cross-file/determinism; include spec-without-implementation and implementation-without-spec fixtures.
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Never auto-pick authority; never suppress one direction of drift silently (§143–§145).
- No fuzzy matching — structural identity only (§9, §181).
- Comparison is read-only over specs 004/006 models; don't re-parse.

# Review Notes

- Verify parameter comparison covers path/query/header/cookie and required-ness both directions.
- Check schema comparison handles $ref-resolved models and doesn't drown in cosmetic ordering diffs.
- Confirm unmatched items on BOTH sides always surface — no silent drops.
