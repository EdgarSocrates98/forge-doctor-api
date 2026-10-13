You are implementing Loop Factory spec `087-contract-compatibility-hardening`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\087-contract-compatibility-hardening.md`
        Spec hash: `9dd51df2413661211af33742c60ad7f1d3499ba45eb18b969bbc148db4625e89`

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
  Phase 7 and items §7/§9/§10.
- Problem: the compat engine classifies changes but adversarial
  coverage is thin — the prompt names concrete cases per protocol
  (request-requiredness, content-type narrowing, discriminator,
  oneOf shifts; GraphQL arg/nullability/interface/union/enum;
  gRPC field-number reuse/reserved/wire-type/oneof/renumbering/
  streaming/package moves; AsyncAPI message/channel/operation/
  correlation/bindings). Client impact lacks Feign/generated-
  client/grpc-stub/graphql-doc detection; ServiceGraph has no
  adversarial identity tests; DeprecationReadiness does not exist.
- Out of scope: new check-id families wholesale (extend catalogs
  where a case truly needs it); runtime enforcement; auto-fix.
- Review failure: adversarial cases that all land on BREAKING or
  all on POTENTIALLY — the taxonomy's value is *distinction*;
  client impact that assumes callers; fuzzy identity joins.
- Riskiest assumption: the engine can keep classification honest
  when input evidence is partial — RESOLVED: every classification
  carries evidence refs; missing evidence → POTENTIALLY with
  unknowns, never BREAKING.
- Smallest acceptable: adversarial test matrix per protocol
  (named cases below), client-impact extractor coverage for
  Feign/axios/requests/httpx/generated/grpc/graphql-doc,
  ServiceGraph adversarial tests, DeprecationReadiness model,
  docs update.

# Context

Phase 7. Existing: `checks/compat/engine.py` +
`catalog.py` (BREAKING/POTENTIALLY_BREAKING/NON_BREAKING),
GraphQL/gRPC/AsyncAPI check modules, `analyzers/clients/` for
python+javascript, `core/graph.py` ServiceGraph, `change/` models.
Missing: the adversarial matrix, client-kind breadth, identity-
hardening tests, deprecation readiness surface.

# Acceptance Criteria

- `tests/test_compat_adversarial.py`: named cases per protocol —
  OpenAPI: required request field add/remove, optional response
  field removal, content-type narrowing, security-scheme change,
  oneOf/anyOf/allOf reshuffle, nullable flip, enum add/remove,
  additionalProperties tighten, discriminator change; each
  asserting the expected class AND evidence presence.
  GraphQL: field removal, arg requiredness, nullable→non-null
  output, interface member removal, union member removal, enum
  value removal, directive change — classified + evidenced.
  gRPC: field-number reuse vs reserve, wire-incompatible type,
  oneof member add/remove, enum renumbering, streaming mode
  change, package/service rename — classified + evidenced.
  AsyncAPI: message schema break, channel removal, operation
  semantics change, correlation id change, binding change —
  classified + evidenced.
- Classification stays honest: a case with missing/partial
  evidence classifies POTENTIALLY with recorded unknowns, never
  BREAKING; test asserts the unknown is carried on the event.
- Client impact depth: `analyzers/clients/` detects call sites for
  Feign (`@FeignClient`/`@RequestLine`), axios, requests, httpx,
  generated OpenAPI clients (`openapi_client`/`*_api` imports or
  generated markers), gRPC stubs (`*_pb2`/`_grpc` imports +
  channel calls), GraphQL query documents (`.graphql` files +
  `gql` usage). Each new kind has fixture + test; when a real
  client corpus exists, confirmed-impact vs potential-impact is
  asserted separately.
- ServiceGraph adversarial tests (`test_service_graph.py`
  extension or new): duplicate operation ids, same route string in
  two services, same service name in two repos, cross-file graphs,
  missing implementation (route declared, no handler → unknown),
  unknown client (calls observed, no client artifact → unknown);
  no identity join uses fuzzy matching — a test asserts ids are
  exact canonical matches.
- `DeprecationReadiness` model + `deprecation readiness` surface
  (report projection or change-model field): known_clients,
  observed_traffic, replacement, sunset_date, unknown_clients —
  emitted with unknowns when signals absent; CLI/SDK exposure
  only if a real surface exists — otherwise model + report field
  + test, documented as analytical.
- `docs/compatibility.md` updated: taxonomy decision table per
  protocol, unknown-first policy, client-impact coverage table.
- pytest/ruff/mypy pass.

# Constraints

- Evidence first: every classification carries refs; no heuristic
  upgrades from "probably breaking".
- New client extractors must not invent hits — evidence
  requirements identical to existing extractors.
- Stay in existing check-id namespaces; catalog additions get
  rationale comments, not new families.
