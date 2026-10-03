"""Spec 033 — IaC/Kubernetes evidence (§74-76)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.iac import (
    K8sKind,
    infra_graph,
    load_infra_model,
)
from forge_doctor_api.core.context import ProjectContext

_K8S = """\
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: web-ing}
spec:
  rules:
    - http:
        paths:
          - path: /pay
            backend:
              service: {name: web-svc, port: {number: 80}}
---
apiVersion: v1
kind: Service
metadata: {name: web-svc, labels: {app: web}}
spec:
  selector: {app: web}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web-dep, labels: {app: web}}
spec:
  selector:
    matchLabels: {app: web}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: web-hpa}
spec: {}
"""

_TF = 'resource "aws_api_gateway_rest_api" "pay" {}\n'

_CHART = "name: payments-chart\nversion: 1.0.0\n"

_CFN = 'AWSTemplateFormatVersion: "2010-09-09"\nResources: {}\n'


def _ctx(root: Path, files: dict[str, str]) -> ProjectContext:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext(root=root)


class TestKubernetes:
    def test_kinds_extracted(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"k8s.yaml": _K8S})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        kinds = {r.kind for r in model.kubernetes}
        assert kinds == {
            K8sKind.INGRESS, K8sKind.SERVICE, K8sKind.DEPLOYMENT,
            K8sKind.HPA}

    def test_ingress_service_deployment_chain(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"k8s.yaml": _K8S})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        pairs = {(c.source, c.target) for c in model.chains}
        assert ("Ingress/web-ing", "Service/web-svc") in pairs
        assert ("Service/web-svc", "Deployment/web-dep") in pairs
        sel = [c for c in model.chains if c.target == "Deployment/web-dep"]
        assert sel[0].via.startswith("selector:")

    def test_missing_backend_is_unknown_not_guessed(self, tmp_path) -> None:
        orphan = """\
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: orphan-ing}
spec:
  rules:
    - http:
        paths:
          - backend: {service: {name: ghost}}
"""
        ctx = _ctx(tmp_path, {"orphan.yaml": orphan})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        assert any("ghost" in (u.missing or "") for u in model.unknowns)

    def test_httproute_backendrefs(self, tmp_path) -> None:
        doc = """\
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: {name: rt}
spec:
  rules:
    - backendRefs: [{name: web-svc, port: 80}]
---
apiVersion: v1
kind: Service
metadata: {name: web-svc}
spec: {selector: {app: web}}
"""
        ctx = _ctx(tmp_path, {"gw.yaml": doc})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        assert ("HTTPRoute/rt", "Service/web-svc") in {
            (c.source, c.target) for c in model.chains}


class TestIac:
    def test_terraform_resource_line(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"main.tf": _TF})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        iac = model.iac[0]
        assert iac.iac_kind == "terraform"
        assert iac.type_name == "aws_api_gateway_rest_api"
        assert iac.name == "pay" and iac.parsed

    def test_helm_chart(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"charts/pay/Chart.yaml": _CHART})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        assert model.iac[0].iac_kind == "helm"
        assert model.iac[0].name == "payments-chart"

    def test_cloudformation_recorded_not_parsed(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"stack.yaml": _CFN})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        iac = model.iac[0]
        assert iac.iac_kind == "cloudformation" and not iac.parsed
        assert model.issues

    def test_deterministic(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"k8s.yaml": _K8S, "main.tf": _TF})
        files = sorted(ctx.iter_files())
        assert load_infra_model(ctx, files) == load_infra_model(ctx, files)


class TestGraphLinkage:
    def test_deployed_as_edge_on_exact_match(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"k8s.yaml": _K8S})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        entities, edges = infra_graph(
            model, ["service:python:web-dep", "service:python:other"])
        assert len(entities) == 1
        assert entities[0].id == "deployment:k8s:web-dep"
        edge = edges[0]
        assert edge.kind == "DEPLOYED_AS"
        assert edge.target_id == "service:python:web-dep"
        assert edge.evidence

    def test_no_match_no_edge(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"k8s.yaml": _K8S})
        model = load_infra_model(ctx, sorted(ctx.iter_files()))
        entities, edges = infra_graph(model, ["service:python:unrelated"])
        assert entities == () and edges == ()
