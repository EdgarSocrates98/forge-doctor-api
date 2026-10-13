Review Loop Factory spec `012-graphql` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\012-graphql.md`

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

- Owner: project owner; decisions sourced from §22, §23, §24, §128, §184.
- Problem: GraphQL schema + resolver surface needs contract intelligence, incl. its distinctive breaking-change shapes.
- Out of scope: federation/subgraph composition, live introspection queries.
- Review failure: N+1 asserted from static evidence alone (§23 forbids it), magic complexity numbers (§24), weak-marker GraphQL detection.
- Riskiest assumption: parser strategy — RESOLVED: `graphql-core` as an optional extra (§3 extras-for-specialized-parsers). It tracks the normative GraphQL spec precisely; a hand-rolled SDL parser risks subtle grammar divergence (block strings, directives, descriptions). Core package must import it lazily and degrade gracefully to UNKNOWN findings when absent.
- Smallest acceptable: SDL + introspection-export → `GraphQLProjectModel`; GQL001–010 as specified; `GraphQLQueryShape` with transparent metrics.

# Context

GraphQL uses the current spec (September 2025 edition) as normative base (§22, §128). `GraphQLProjectModel` models types, interfaces, unions, enums, scalars, queries, mutations, subscriptions, directives, arguments, resolvers, deprecations (§22). `GraphQLQueryShape` (§24): depth, field_count, list_expansions, resolver_count, estimated_complexity — no magic scores. Client query parsing (§184) upgrades usage evidence where available.

# Acceptance Criteria

- Parse GraphQL SDL and introspection JSON exports into `GraphQLProjectModel` (§22 fields), resolvers linked when statically discoverable (framework evidence or explicit mapping files).
- Graph materialization: GraphQLType, GraphQLResolver entities + schema relationships.
- Checks GQL001–010 per §23: deprecated field with active clients; field removed; required argument added; nullable→non-null; enum value removed; resolver without authorization evidence; unbounded list field; deep traversal candidate; N+1 candidate; introspection exposure policy mismatch — all emitted with correct evidence levels.
- GQL009 (N+1) and depth/traversal findings are STATIC *candidates* until RUNTIME evidence confirms (§23, §102).
- `GraphQLQueryShape` computes §24 metrics from parsed client queries (§184) — transparent formula, no opaque score.
- Breaking-change classification for schema diffs routes through the unified compat engine classes (§121) with GraphQL-specific rules (GQL002–005 semantics).
- Tests per §202 incl. adversarial (GraphQL-looking JSON, proto-like comments per §100).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- `graphql-core` (if used) must be an optional extra — core stays lean (§3).
- Static evidence stays candidate-level for runtime-flavored findings (§102).
- No introspection against live endpoints — exports only (§1).

# Review Notes

- Verify nullable→non-null detection handles input vs output positions separately (mirrors §123 request/response split).
- Confirm introspection-policy check is config-evidence-based, not assumed from defaults.
