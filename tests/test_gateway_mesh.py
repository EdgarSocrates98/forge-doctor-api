"""Spec 032 — gateway/mesh declared-config model (§71-73, §196)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.gateway import (
    GatewayDialect,
    MeshVendor,
    load_gateway_models,
)
from forge_doctor_api.core.context import ProjectContext

_KONG = """\
_format_version: "3.0"
services:
  - name: payments
    url: http://payments-svc:8080
    retries: 2
    routes:
      - name: payments-route
        paths: ["/pay"]
        methods: ["GET", "POST"]
    plugins:
      - name: key-auth
      - name: rate-limiting
        config: {minute: 100}
"""

_NGINX = """\
server {
    listen 80;
    location /api/ {
        proxy_pass http://backend;
        proxy_read_timeout 30s;
        limit_req zone=one burst=5;
        add_header X-Upstream always;
    }
}
"""

_ENVOY = """\
static_resources:
  listeners:
    - name: main
  clusters:
    - name: backend
      type: STRICT_DNS
      connect_timeout: 5s
"""

_AWS = """\
openapi: "3.0.1"
info: {title: pay-api, version: "1"}
paths:
  /pay:
    get:
      security:
        - api_key: []
      x-amazon-apigateway-integration:
        type: http_proxy
        uri: http://backend/pay
x-amazon-apigateway-policy: {Version: "2012-10-17"}
"""

_MESH = """\
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata: {name: vs}
spec:
  http:
    - route:
        - destination: {host: payments, subset: v1}
          weight: 90
        - destination: {host: payments, subset: v2}
          weight: 10
      retries: {attempts: 3}
      timeout: 2s
---
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: {name: dr}
spec:
  host: payments
  trafficPolicy:
    outlierDetection: {consecutive5xxErrors: 5}
---
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata: {name: pa}
spec:
  mtls: {mode: STRICT}
"""


def _ctx(root: Path, files: dict[str, str]) -> ProjectContext:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext(root=root)


def _files(ctx: ProjectContext) -> list[str]:
    return sorted(ctx.iter_files())


class TestGatewayModel:
    def test_kong(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"kong.yaml": _KONG})
        gws, _, _ = load_gateway_models(ctx, _files(ctx))
        assert len(gws) == 1
        gw = gws[0]
        assert gw.dialect is GatewayDialect.KONG
        assert gw.routes[0].path == "/pay"
        assert gw.routes[0].upstream == "payments"
        assert gw.upstreams[0].name == "payments"
        assert "http://payments-svc:8080" in gw.upstreams[0].detail
        assert any(p.name == "key-auth" for p in gw.plugins)
        assert gw.auth and gw.rate_limits and gw.retries

    def test_nginx(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"nginx.conf": _NGINX})
        gws, _, _ = load_gateway_models(ctx, _files(ctx))
        gw = gws[0]
        assert gw.dialect is GatewayDialect.NGINX
        assert gw.routes[0].path == "/api/"
        assert gw.routes[0].upstream == "http://backend"
        assert gw.rate_limits and gw.timeouts and gw.transformations

    def test_envoy(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"envoy.yaml": _ENVOY})
        gws, _, _ = load_gateway_models(ctx, _files(ctx))
        assert gws[0].dialect is GatewayDialect.ENVOY
        assert gws[0].upstreams[0].name == "backend"

    def test_aws_apigateway(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"api.yaml": _AWS})
        gws, _, _ = load_gateway_models(ctx, _files(ctx))
        gw = gws[0]
        assert gw.dialect is GatewayDialect.AWS_API_GATEWAY
        assert gw.routes[0].path == "GET /pay"
        assert gw.routes[0].upstream == "http://backend/pay"
        assert gw.auth and gw.policies

    def test_unrelated_yaml_ignored(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"settings.yaml": "foo: bar\n"})
        gws, meshes, unknowns = load_gateway_models(ctx, _files(ctx))
        assert gws == () and meshes == () and unknowns == ()

    def test_gatewayish_garbage_records_unknown(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"kong.yaml": "kong: [unclosed\n"})
        gws, _, unknowns = load_gateway_models(ctx, _files(ctx))
        assert gws == ()
        assert unknowns and unknowns[0].subject == "kong.yaml"

    def test_deterministic(self, tmp_path) -> None:
        files = {"kong.yaml": _KONG, "nginx.conf": _NGINX}
        ctx = _ctx(tmp_path, files)
        a = load_gateway_models(ctx, _files(ctx))
        b = load_gateway_models(ctx, _files(ctx))
        assert a == b


class TestMeshModel:
    def test_istio(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"istio.yaml": _MESH})
        _, meshes, _ = load_gateway_models(ctx, _files(ctx))
        assert len(meshes) == 1
        mesh = meshes[0]
        assert mesh.vendor is MeshVendor.ISTIO
        assert mesh.routing and mesh.retries and mesh.timeouts
        assert mesh.traffic_splits and mesh.circuit_breakers and mesh.mtls
        assert mesh.evidence

    def test_no_mesh_markers(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"kong.yaml": _KONG})
        _, meshes, _ = load_gateway_models(ctx, _files(ctx))
        assert meshes == ()
