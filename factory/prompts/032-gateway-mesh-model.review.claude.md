Review Loop Factory spec `032-gateway-mesh-model` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\032-gateway-mesh-model.md`

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

- Owner: project owner; decisions sourced from §71, §72, §73, §196.
- Problem: gateway capability packs and `gateway_routes` exist, but there
  is no declared `GatewayModel` (routes/upstreams/plugins/auth/
  rate_limits/retries/timeout/transformations/policies) parsed from
  gateway config files, nor a `ServiceMeshModel` for mesh evidence.
- Out of scope: live gateway admin APIs; vendor-specific full parsers —
  this is *evidence extraction* from committed config files, not a Kong
  schema implementation.
- Review failure: inferring gateway behavior the config doesn't declare,
  or matching files by name alone without content markers.
- Riskiest assumption: config dialect coverage — RESOLVED: recognize a
  bounded, explicit set (Kong declarative YAML, Envoy YAML, AWS API
  Gateway JSON/YAML export markers, NGINX conf directives); anything else
  → detection issue + UnknownFact.
- Smallest acceptable: `GatewayModel`+`MeshModel` parsers for the bounded
  formats, twin/drift integration of the parsed routes, tests.

# Context

§72: `GatewayModel` carries routes, upstreams, plugins, auth,
rate_limits, retries, timeout, transformations, policies. §71 lists
adapters (AWS API Gateway first per §196, then Kong/Envoy/NGINX); the
knowledge packs already declare each platform's capabilities — this spec
models the *observed* config, not capabilities. §73 (marked "Futuro")
models mesh routing/retry/timeout/circuit-breaker/mTLS/traffic-split —
implement a minimal evidence-bearing `ServiceMeshModel` from config
markers (e.g. Istio `networking.istio.io` kinds), not a full mesh engine.

# Acceptance Criteria

- `GatewayModel` per §72: declared routes (path→upstream), upstreams,
  plugins, auth, rate_limits, retries, timeout, transformations,
  policies — each field a tuple of evidence-bearing records; absent
  sections are empty tuples, unknown dialects → `issues`/`unknowns`.
- Parsers for: Kong declarative YAML (`services:`/`routes:`/`plugins:`),
  Envoy YAML (`static_resources`/`listeners`), AWS API Gateway export
  (`x-amazon-apigateway` markers / `swagger`+apigw extensions), NGINX
  conf (`server`/`location`/`proxy_pass` blocks, line-level evidence).
- `ServiceMeshModel`: detected mesh (istio|envoy|linkerd|unknown),
  evidence records for routing/retry/timeout/circuit-breaker/mTLS/
  traffic-split config keys; no markers → empty model, no finding.
- `twin/drift.gateway_routes` keeps working; new parsers feed it the
  same route map (no parallel route vocabulary).
- Determinism + offline; malformed files → issue records, not crashes.
- Tests: each dialect's positive case, dialect-mismatch negatives,
  mesh markers, determinism; pytest/ruff/mypy pass.

# Constraints

- Detection requires content markers, not filenames.
- Everything declared-or-unknown: no inferred defaults.
- `GatewayModel` must not conflate with capability packs (§130) —
  packs = what a platform *supports*, model = what a config *declares*.
