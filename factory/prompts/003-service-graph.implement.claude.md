You are implementing Loop Factory spec `003-service-graph`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\003-service-graph.md`
        Spec hash: `d28a69787db23068a15066a8468ee607d0af301656ecaddff7d7ec330a738c5f`

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

- Owner: project owner; decisions sourced from §8, §9, §58 of `prompt_evo_inicial.md`.
- Problem: all intelligence lands on one graph — entities, relationships, canonical identity (§225 Phase C).
- Out of scope: contract graph semantics (spec 007), capability engine (spec 027), topology analysis beyond storing it.
- Review failure: fuzzy identity merging, non-canonical IDs accepted, nondeterministic iteration, missing entity/relationship kinds from §8.
- Riskiest assumption: entity kind list is sufficient — mitigate by making the enum extensible without breaking serialized graphs.
- Smallest acceptable: enums + models + in-memory graph with deterministic queries and serialization.

# Context

Phase C (§225). `ServiceGraph` is the API counterpart of `DataPlatformGraph` (§8). Identity is canonical: `{kind}:{domain}:{identifier}` (§9) — e.g. `service:python:payments`, `endpoint:http:GET:/payments/{id}`. Fuzzy merging is forbidden. `ServiceTopology` (§58) records the service→service dependency shape the graph exposes.

# Acceptance Criteria

- `EntityKind` enum covers §8.1: Service, API, Endpoint, Operation, Schema, Message, Event, Topic, Queue, Subscription, Client, Gateway, LoadBalancer, IdentityProvider, Credential, Deployment, Runtime, Database, Cache, ExternalAPI, Webhook, GraphQLType, GraphQLResolver, GrpcService, GrpcMethod, ProtoMessage, AsyncChannel, Policy, SLO.
- `RelationshipKind` enum covers §8.2: EXPOSES, CALLS, ROUTES_TO, IMPLEMENTS, CONSUMES, PRODUCES, PUBLISHES, SUBSCRIBES, READS, WRITES, AUTHENTICATES_WITH, AUTHORIZED_BY, DEPENDS_ON, USES, RETURNS, ACCEPTS, GOVERNS, DEPLOYED_AS, FRONTED_BY, RETRIES, FALLS_BACK_TO.
- `Entity`/`Relationship` models validate canonical ID shape `{kind}:{domain}:{identifier}`; invalid IDs rejected.
- `ServiceGraph` supports: add entity/edge, get by id, list by kind, neighbors by relationship kind, deterministic serialization (sorted output).
- Duplicate canonical ID = same node (idempotent add); never merge distinct IDs.
- `ServiceTopology` view: service-level CALLS/DEPENDS_ON adjacency for §58-style diagrams.
- Tests per §202: positive/negative/malformed/determinism; cycle in edges does not break traversal.

# Constraints

- No fuzzy merge, no similarity matching, no auto-linking by name (§9).
- Graph stays in-memory + serializable; no database, no external graph lib required unless stdlib-insufficient (prefer none).
- No inference edges — only edges an analyzer explicitly records with evidence.

# Review Notes

- Determinism: iterate/serialize in sorted order everywhere.
- Confirm unknown/uncertain relationships are representable without pretending certainty (UNKNOWN semantics, §1).
