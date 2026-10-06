Review Loop Factory spec `033-iac-kubernetes` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\033-iac-kubernetes.md`

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

- Owner: project owner; decisions sourced from §74, §75, §76.
- Problem: the engine sees contracts/routes/runtime but not the
  infrastructure layer that fronts APIs — Kubernetes
  Service/Ingress/Gateway-API/Deployment/HPA/ConfigMap (§75), IaC
  manifests (§74: Terraform now; CloudFormation explicitly "future"),
  and the Ingress→Service→Deployment→operations chain (§76).
- Out of scope: HCL evaluation of Terraform; CloudFormation (prompt
  defers it); applying/validating cluster state — evidence extraction
  from committed manifests only.
- Review failure: matching `values.yaml` or a random `deployment.yaml`
  by name; linking Ingress→Service without selector/label evidence.
- Riskiest assumption: label/selector equality is the honest link —
  RESOLVED: a link exists only when `spec.selector`/`metadata.labels`
  values match byte-for-byte; else the node is recorded unlinked.
- Smallest acceptable: k8s manifest detection + resource model +
  selector-based chain + Terraform resource detection; tests.

# Context

§75 detection list: `Service`, `Ingress`, `Gateway API`
(`gateway.networking.k8s.io` kinds), `Deployment`, `HPA`
(`autoscaling/` kinds), `ConfigMap`. §76 example chain:
`Ingress → Service → Deployment → API operations`. §74 IaC adapters:
Terraform (`.tf` files — record `resource "TYPE" "NAME"` declarations
as evidence; no expression evaluation), Kubernetes manifests, Helm
values (`values.yaml` + sibling `Chart.yaml`).

# Acceptance Criteria

- `KubernetesManifest` records: kind, apiVersion, name, namespace,
  evidence location — for Service/Ingress/Gateway/Deployment/HPA/
  ConfigMap plus a generic `Other` bucket for unrecognized `kind:`.
- `KubernetesChain`: `ingress/host → service → deployment` links built
  only on selector/label equality or explicit `serviceName`/`backend`
  references; unresolved hops → `UnknownFact`, not inference.
- `IacModel`: Terraform resources (type, name, file evidence) parsed
  from `*.tf` text via a conservative `resource "…"` line scan;
  Helm charts detected via `Chart.yaml`; CloudFormation files recorded
  as `issues` ("deferred per §74") not parsed.
- API linkage: when a manifest namespace/name/labels match a scanned
  service identity, emit a `serves`-style edge into `ServiceGraph` —
  otherwise leave the infra node unlinked (no fuzzy match).
- Determinism, offline, malformed YAML → issue records.
- Tests: each resource kind, the §76 chain positive+negative cases,
  Terraform detection, Helm detection, CFN-deferred; pytest/ruff/mypy.

# Constraints

- No cluster API, no HCL evaluation, no live state.
- Links only on declared identifiers — selector equality, explicit
  backend names — never name similarity heuristics.
