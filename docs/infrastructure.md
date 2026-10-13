# Infrastructure intelligence

The engine models the *declared* infrastructure surface around an API —
gateway configuration, service-mesh markers, Kubernetes manifests, and
IaC files — from committed artifacts only. It never calls a cluster API,
a gateway admin endpoint, or a cloud API.

Two hard rules apply everywhere on this page:

- **Detection is content-marker based, never filename based.** A file
  named `kong.yaml` that contains no Kong structure is ignored; a file
  named `anything.yaml` containing `x-amazon-apigateway-*` markers is an
  AWS API Gateway export.
- **Declared-or-unknown.** Every field is either evidence-bearing or
  `None`/an `UnknownFact`. The parsers never infer a plugin, a backend,
  or a default the config did not write down.

## Gateway model (§71–§72, §196)

`load_gateway_models(context, files)` returns
`(gateways, meshes, unknowns)`. Each `GatewayModel` names its dialect
and carries one evidence-bearing `ConfigEntry`/`GatewayRoute` tuple per
§72 facet:

```text
dialect        kong | envoy | aws-api-gateway | nginx
routes         declared path → upstream mappings
upstreams      backend targets (service url, cluster, proxy_pass)
plugins        declared plugin/policy names
auth           auth plugins, security blocks, auth directives
rate_limits    rate-limiting declarations
retries        retry declarations
timeouts       connect/read/send timeout declarations
transformations  header/rewrite/return directives
policies       vendor policy blocks (e.g. x-amazon-apigateway-*)
unknowns       anything gateway-flavoured that did not parse
```

Recognized dialects (bounded on purpose — anything else becomes an
`UnknownFact`, not a guess):

| Dialect | Content markers |
|---|---|
| Kong declarative | `_format_version`, `services:` with `routes:`/`plugins:` |
| Envoy | `static_resources`, `listeners`, `clusters` |
| AWS API Gateway | `x-amazon-apigateway*` extensions on an OpenAPI export |
| NGINX | `.conf` files with `location`/`proxy_pass`/rate-limit directives |

A file that looks gateway-flavoured but fails YAML parsing records an
`UnknownFact` ("file has gateway markers but invalid YAML") instead of
being silently skipped — silent skipping is how coverage gaps hide.

### Feeding the twin, not replacing it

`twin/drift.gateway_routes()` merges dialect-parsed routes into the same
`path → declaring-file` map it always produced. The §64
`ROUTING_DRIFT` check ("gateway route has no declared contract
operation") therefore sees Kong/Envoy/AWS/NGINX routes without learning
a second route vocabulary.

### What the model is not

The `GatewayModel` records what a config *declares*. What a platform is
*capable of* lives in the gateway capability packs
(`docs/knowledge-packs.md`, §130). A Kong config that declares no
`rate-limiting` plugin yields an empty `rate_limits` tuple — it does
not mean rate limiting is impossible on Kong, and it does not produce a
finding.

## Service mesh (§73)

`ServiceMeshModel` is marker-driven minimal evidence, not a mesh engine.
Files containing `networking.istio.io`, `sidecar.istio.io`, `linkerd.io`,
or `envoyproxy.io` markers produce a model with per-key evidence
records for the six §73 facets:

```text
routing · retries · timeouts · circuit_breakers · mtls · traffic_splits
```

Each record is a `ConfigEntry` carrying the matched line and location.
No markers → empty model, no finding. Absent mesh evidence is absence
of *input*, not an absence verdict.

## Kubernetes + IaC (§74–§76)

`load_infra_model(context, files)` builds an `InfraModel`:

```text
kubernetes   KubernetesResource per manifest object
chains       ChainLink hops (front → Service → Deployment)
iac          IacResource records (terraform | helm | cloudformation)
issues       deferred/unsupported input notices
unknowns     unresolved chain hops
```

### Kubernetes resources

Every YAML document with `apiVersion` + `kind` + `metadata.name` is
recorded — `Service`, `Ingress`, `Gateway`/`HTTPRoute`
(`gateway.networking.k8s.io`), `Deployment`, `HorizontalPodAutoscaler`,
`ConfigMap`, plus a generic `Other` bucket for unrecognized kinds.
Selectors and backend references are captured as data.

### Chains — identifier equality only

§76 chains are built exclusively on declared identifiers:

- `Ingress`/`HTTPRoute`/`Gateway` → `Service`: the manifest's
  `backend.service.name` / `serviceName` / `backendRefs[].name`.
- `Service` → `Deployment`: byte-equal `spec.selector` ↔
  `matchLabels` overlap.

An `Ingress` pointing at a `Service` that is not in scope records an
`UnknownFact` — the hop is *unknown*, not inferred from name
similarity. A `Service` whose selector matches no `Deployment` records
one too. This is the difference between "we could not resolve the hop"
and "the hop does not exist"; the model reports the first.

### IaC

- **Terraform**: conservative `resource "TYPE" "NAME"` line scan of
  `*.tf` — no HCL evaluation, no provider calls.
- **Helm**: `Chart.yaml` presence records the chart name.
- **CloudFormation**: files with `AWSTemplateFormatVersion`/`AWS::`
  markers are recorded as `IacResource(parsed=False)` plus an issue
  ("deferred per §74") — declared unsupported, not ignored.

### Linking to the service graph (§76)

`infra_graph(infra, service_ids)` emits `deployment:k8s:<ns>.<name>`
entities and `DEPLOYED_AS` edges **only** when a manifest
`metadata.name` is byte-equal to the identifier of a scanned
`service:<domain>:<name>` entity. No match → the infra node stays
unlinked. The graph keeps its core promise: edges are recorded, never
inferred.

## Testing

`tests/test_gateway_mesh.py`, `tests/test_iac.py` cover each dialect's
positive case, dialect-mismatch negatives, mesh markers, the §76 chain
positive + negative, Terraform/Helm/CFN handling, graph linkage, and
determinism.

## IaC depth (spec 055)

`analyzers/iac/hcl.py` is a bounded Terraform scanner over the shared
`textscan` stripper: comments and heredocs are stripped positionally,
top-level block headers (`resource "aws_lb" "x"`) and simple
`key = literal` attributes are extracted with per-field file/line
evidence. Dynamic or nested expressions are never guessed — they
become `None` plus an `UnknownFact`. Literal `count > 0` establishes
resource existence; a dynamic `count` leaves existence unknown.

`analyzers/iac/cloudformation.py` loads CloudFormation YAML safely
through custom `!Ref`/`!GetAtt`/`!Sub` constructors — intrinsic values
are recorded as dynamic + `UnknownFact`, `Resources` are extracted
with type/property evidence. Malformed HCL/YAML never crashes the
scan; commented blocks and strings containing `resource "aws_lb"`
produce nothing.

## Gateway depth (spec 056)

Dialects: Kong (services/routes/plugins), Envoy (listeners/routes/
clusters), Nginx (`location`/`upstream`), Traefik (routers/services/
middlewares), AWS API Gateway, and declared mesh traffic edges
(Istio `VirtualService`/`DestinationRule`, Linkerd `ServiceProfile`).

The existence rule is uniform: a route whose target does not resolve
to a *declared* upstream/service stays in the model with
`service=None` and an `UnknownFact` — name-matched edges are never
created. Commented directives, `location` text inside string values,
and template variables produce no routes and no entities.
