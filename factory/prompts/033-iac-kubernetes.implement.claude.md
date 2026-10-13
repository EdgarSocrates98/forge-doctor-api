You are implementing Loop Factory spec `033-iac-kubernetes`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\033-iac-kubernetes.md`
        Spec hash: `96555ef61e87360fa052e167a057c3a69a2dbdc002f4b750b474c7b390023548`

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
