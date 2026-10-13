---
id: 056-gateway-depth
title: Gateway/mesh depth — route policies, rate limits, auth edges, upstreams
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §64-§66.
- Problem: gateway model is a marker surface (detects Kong/Envoy/
  Nginx/Traefik presence + coarse route hints); §64-66 ask for
  route→upstream binding, rate-limit/auth-plugin extraction, mesh
  traffic-policy edges.
- Out of scope: new dialects (the four bounded dialects stay); live
  gateway introspection — static config only.
- Review failure: plugin names hardcoded as findings instead of
  extracted fields; a mesh edge created because two services have
  similar names; parse of a dialect-specific file attributed to the
  wrong dialect.
- Riskiest assumption: dialect field scope — RESOLVED: per-dialect
  extractors bounded to route bindings + plugin/policy literal fields
  (rate limiting, auth plugin names, upstream hosts) as candidates;
  anything templated → None+unknown; documented per dialect.
- Smallest acceptable: GatewayModel gains evidence-backed routes
  (path/prefix→service), policies (rate-limit/auth candidate list),
  upstreams; mesh gains traffic-policy edges where config declares
  them; tests incl. adversarial + no-FP on non-gateway yaml.

# Context

§64-§66: gateway depth and mesh edges. Evidence-first: declared
policies only, candidates for everything else. Same adversarial YAML
class as spec 032 — the random-named yaml FP must stay dead.

# Acceptance Criteria

- `gateway.py` per-dialect extractors: Kong (services+routes+plugins),
  Envoy (listeners/routes/clusters), Nginx (location/upstream),
  Traefik (routers/services/middlewares) — emitting
  `GatewayRoute{path_prefix, service?, evidence}`,
  `GatewayPolicy{kind: rate_limit|auth|cors|other, params literals,
  evidence}`, `GatewayUpstream{name, host?, evidence}`.
- Mesh: `istio.py`/`linkerd` config → traffic-policy edges
  (VirtualService/DestinationRule host→subset, Linkerd ServiceProfile)
  as declared edges only.
- Existence rule: a route binding whose target service cannot be
  resolved → upstream with `service=None` + UnknownFact — never a
  name-matched edge.
- Adversarial: commented config, string-fake markers, template
  variables → CANDIDATE/UNKNOWN; random yaml still produces no
  gateway entities.
- pytest/ruff/mypy pass.

# Constraints

- No name-similarity edges; dynamic values → unknowns.
- Dialect detection stays marker-based (no guessing).
