"""Gateway + service-mesh config extraction (§71-73, §196).

Detection is content-marker based — never filename-based. Supported
declared formats: Kong declarative YAML, Envoy YAML, AWS API Gateway
exports, NGINX conf. Anything else with gateway-ish hints records an
UnknownFact, not a guess.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from forge_doctor_api.analyzers.gateway.model import (
    ConfigEntry,
    GatewayDialect,
    GatewayModel,
    GatewayRoute,
    MeshVendor,
    ServiceMeshModel,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)

_YAML = {".yaml", ".yml"}
_CONF = {".conf"}

_MESH_MARKERS = {
    MeshVendor.ISTIO: ("networking.istio.io", "sidecar.istio.io",
                       "istio.io/"),
    MeshVendor.LINKERD: ("linkerd.io",),
    MeshVendor.ENVOY: ("envoyproxy.io", "envoy.api.v2"),
}

_MESH_KEYS = {
    "routing": ("httpRoute", "route:", "VirtualService", "destination:"),
    "retries": ("retries:", "attempts:"),
    "timeouts": ("timeout:", "timeoutSeconds"),
    "circuit_breakers": ("circuitBreaker", "outlierDetection"),
    "mtls": ("PeerAuthentication", "mtls", "tls:"),
    "traffic_splits": ("weight:", "TrafficSplit", "canary"),
}


def _loc(path: str, line: int | None = None) -> SourceLocation:
    return SourceLocation(path=path, line=line)


def _entry(path: str, lineno: int | None, name: str, detail: str) -> ConfigEntry:
    return ConfigEntry(name=name, detail=detail,
                       location=_loc(path, lineno))


def _yaml_docs(text: str) -> list[dict[str, Any]]:
    try:
        docs = [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError:
        return []
    return docs


def _walk(obj: object, pred: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if pred(obj):
            out.append(obj)
        for v in obj.values():
            out.extend(_walk(v, pred))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk(v, pred))
    return out


# -- Kong declarative -------------------------------------------------------


def _parse_kong(path: str, doc: dict[str, Any]) -> GatewayModel:
    routes: list[GatewayRoute] = []
    upstreams: list[ConfigEntry] = []
    plugins: list[ConfigEntry] = []
    auth: list[ConfigEntry] = []
    rate_limits: list[ConfigEntry] = []
    retries: list[ConfigEntry] = []
    timeouts: list[ConfigEntry] = []
    policies: list[ConfigEntry] = []

    for svc in _walk(doc, lambda d: "routes" in d or "host" in d):
        if "host" in svc or "url" in svc:
            target = svc.get("url") or svc.get("host")
            upstreams.append(_entry(
                path, None, str(svc.get("name") or target or "service"),
                f"target={target}"))
            for key in ("retries", "connect_timeout", "read_timeout",
                        "write_timeout"):
                if key in svc:
                    bucket = retries if key == "retries" else timeouts
                    bucket.append(_entry(
                        path, None, str(svc.get("name") or target or "?"),
                        f"{key}={svc[key]}"))
        for r in svc.get("routes") or ():
            if isinstance(r, dict):
                for p in r.get("paths") or ():
                    routes.append(GatewayRoute(
                        path=str(p),
                        upstream=str(svc.get("name") or svc.get("host")),
                        location=_loc(path, None)))
        for plugin in svc.get("plugins") or ():
            if isinstance(plugin, dict):
                name = str(plugin.get("name", "?"))
                plugins.append(_entry(path, None, name, "service plugin"))
                if "key-auth" in name or "jwt" in name or "oauth" in name \
                        or "basic-auth" in name:
                    auth.append(_entry(path, None, name, "auth plugin"))
                if "rate-limiting" in name:
                    rate_limits.append(
                        _entry(path, None, name, "rate-limit plugin"))
    for plugin in _walk(doc, lambda d: set(d) == {"plugins"}):
        for p in plugin.get("plugins") or ():
            if isinstance(p, dict):
                plugins.append(_entry(path, None, str(p.get("name", "?")),
                                      "global plugin"))
                if p.get("name") == "rate-limiting":
                    rate_limits.append(_entry(
                        path, None, "rate-limiting", "global plugin"))
                n = str(p.get("name", ""))
                if any(k in n for k in ("key-auth", "jwt", "oauth2",
                                        "basic-auth", "openid")):
                    auth.append(_entry(path, None, n, "global auth plugin"))
    return GatewayModel(
        dialect=GatewayDialect.KONG, source=_loc(path),
        routes=tuple(routes), upstreams=tuple(upstreams),
        plugins=tuple(plugins), auth=tuple(auth),
        rate_limits=tuple(rate_limits), retries=tuple(retries),
        timeouts=tuple(timeouts), policies=tuple(policies))


# -- Envoy ------------------------------------------------------------------


def _parse_envoy(path: str, doc: dict[str, Any]) -> GatewayModel:
    routes: list[GatewayRoute] = []
    upstreams: list[ConfigEntry] = []
    plugins: list[ConfigEntry] = []
    timeouts: list[ConfigEntry] = []
    retries: list[ConfigEntry] = []
    for lsnr in _walk(doc, lambda d: "route_config" in d):
        rc = lsnr.get("route_config") or {}
        for vh in _walk(rc, lambda d: "routes" in d and "domains" in d):
            for r in vh.get("routes") or ():
                match = (r.get("match") or {}).get("prefix") or \
                    (r.get("match") or {}).get("path")
                route = r.get("route") or {}
                cluster = route.get("cluster") or \
                    (route.get("weighted_clusters") or {})
                routes.append(GatewayRoute(
                    path=str(match or "/"),
                    upstream=str(cluster if isinstance(cluster, str)
                                 else "weighted"),
                    location=_loc(path, None)))
                if route.get("timeout"):
                    timeouts.append(_entry(
                        path, None, str(cluster), f"timeout={route['timeout']}"))
                if route.get("retry_policy"):
                    retries.append(_entry(
                        path, None, str(cluster), "retry_policy"))
    for cl in _walk(doc, lambda d: "load_assignment" in d or
                    ("name" in d and "type" in d)):
        upstreams.append(_entry(
            path, None, str(cl.get("name", "cluster")),
            "cluster"))
    return GatewayModel(
        dialect=GatewayDialect.ENVOY, source=_loc(path),
        routes=tuple(routes), upstreams=tuple(upstreams),
        plugins=tuple(plugins), timeouts=tuple(timeouts),
        retries=tuple(retries))


# -- AWS API Gateway --------------------------------------------------------


def _parse_aws(path: str, doc: dict[str, Any]) -> GatewayModel:
    routes: list[GatewayRoute] = []
    policies: list[ConfigEntry] = []
    auth: list[ConfigEntry] = []
    for pth, item in (doc.get("paths") or {}).items():
        if isinstance(item, dict):
            for method, op in item.items():
                if not isinstance(op, dict):
                    continue
                integ = op.get("x-amazon-apigateway-integration") or {}
                routes.append(GatewayRoute(
                    path=f"{method.upper()} {pth}",
                    upstream=str(integ.get("uri") or integ.get("type")),
                    location=_loc(path, None)))
                if op.get("security") or integ.get("credentials"):
                    auth.append(_entry(
                        path, None, f"{method.upper()} {pth}",
                        "security/credentials declared"))
    for name, secdef in (doc.get("components", {})
                         .get("securitySchemes", {}) or {}).items():
        if isinstance(secdef, dict) and "x-amazon-apigateway" in str(secdef):
            auth.append(_entry(path, None, str(name), "apigw security scheme"))
    for key in doc:
        if str(key).startswith("x-amazon-apigateway"):
            policies.append(_entry(path, None, str(key), "apigw extension"))
    return GatewayModel(
        dialect=GatewayDialect.AWS_API_GATEWAY, source=_loc(path),
        routes=tuple(routes), auth=tuple(auth), policies=tuple(policies))


# -- NGINX ------------------------------------------------------------------


_LOCATION = re.compile(r"^\s*location\s+(?P<loc>\S+)\s*\{")
_PROXY = re.compile(r"^\s*proxy_pass\s+(?P<to>\S+)\s*;")
_LIMIT = re.compile(r"^\s*(limit_req|limit_conn)\b\s*(?P<rest>.*)")
_DIRECTIVE = re.compile(
    r"^\s*(auth_request|auth_basic|client_max_body_size|"
    r"proxy_connect_timeout|proxy_read_timeout|proxy_send_timeout|"
    r"proxy_next_upstream|add_header|return|rewrite)\b\s*(?P<rest>.*)")


def _parse_nginx(path: str, text: str) -> GatewayModel:
    routes: list[GatewayRoute] = []
    upstreams: list[ConfigEntry] = []
    auth: list[ConfigEntry] = []
    rate_limits: list[ConfigEntry] = []
    timeouts: list[ConfigEntry] = []
    retries: list[ConfigEntry] = []
    transforms: list[ConfigEntry] = []
    current: str | None = None
    for i, line in enumerate(text.splitlines(), 1):
        m = _LOCATION.match(line)
        if m:
            current = m["loc"]
            continue
        p = _PROXY.match(line)
        if p and current:
            routes.append(GatewayRoute(
                path=current, upstream=p["to"],
                location=_loc(path, i)))
            upstreams.append(_entry(path, i, p["to"], "proxy_pass target"))
            continue
        if _LIMIT.match(line) and current:
            rate_limits.append(_entry(path, i, current,
                                      line.strip()))
            continue
        d = _DIRECTIVE.match(line)
        if d and current:
            directive = line.strip().split()[0]
            if directive.startswith("auth"):
                auth.append(_entry(path, i, current, directive))
            elif "timeout" in directive:
                timeouts.append(_entry(path, i, current, directive))
            elif directive == "proxy_next_upstream":
                retries.append(_entry(path, i, current, directive))
            elif directive in ("add_header", "rewrite", "return"):
                transforms.append(_entry(path, i, current, directive))
    return GatewayModel(
        dialect=GatewayDialect.NGINX, source=_loc(path),
        routes=tuple(routes), upstreams=tuple(upstreams), auth=tuple(auth),
        rate_limits=tuple(rate_limits), timeouts=tuple(timeouts),
        retries=tuple(retries), transformations=tuple(transforms))


# -- detection + mesh --------------------------------------------------------


def _detect_yaml_dialect(doc: dict[str, Any]) -> GatewayDialect | None:
    if "_format_version" in doc or (
            "services" in doc and any(
                isinstance(s, dict) and "routes" in s
                for s in doc.get("services") or ())):
        return GatewayDialect.KONG
    if "static_resources" in doc or "listeners" in doc:
        return GatewayDialect.ENVOY
    keys = {str(k) for k in doc}
    if any(k.startswith("x-amazon-apigateway") for k in keys) or (
            "paths" in doc and any(
                "x-amazon-apigateway" in str(v) for v in
                (doc.get("paths") or {}).values())):
        return GatewayDialect.AWS_API_GATEWAY
    return None


def _mesh_vendor(text: str) -> MeshVendor:
    for vendor, markers in _MESH_MARKERS.items():
        if any(m in text for m in markers):
            return vendor
    return MeshVendor.UNKNOWN


def _mesh_entries(path: str, text: str) -> ServiceMeshModel:
    vendor = _mesh_vendor(text)
    if vendor is MeshVendor.UNKNOWN:
        return ServiceMeshModel()
    fields: dict[str, list[ConfigEntry]] = {k: [] for k in _MESH_KEYS}
    for i, line in enumerate(text.splitlines(), 1):
        for bucket, keys in _MESH_KEYS.items():
            if any(k in line for k in keys):
                fields[bucket].append(_entry(
                    path, i, line.strip()[:60], bucket))
    return ServiceMeshModel(
        vendor=vendor,
        routing=tuple(fields["routing"]),
        retries=tuple(fields["retries"]),
        timeouts=tuple(fields["timeouts"]),
        circuit_breakers=tuple(fields["circuit_breakers"]),
        mtls=tuple(fields["mtls"]),
        traffic_splits=tuple(fields["traffic_splits"]),
        evidence=(Evidence(
            kind=EvidenceKind.CONFIG, source=path,
            summary=f"{vendor} mesh markers detected"),))


def load_gateway_models(
    context: ProjectContext, files: list[str],
) -> tuple[tuple[GatewayModel, ...], tuple[ServiceMeshModel, ...],
           tuple[UnknownFact, ...]]:
    """Parse declared gateway configs + mesh evidence (§71-73)."""
    gateways: list[GatewayModel] = []
    meshes: list[ServiceMeshModel] = []
    unknowns: list[UnknownFact] = []
    for rel in sorted(files):
        suffix = Path(rel).suffix.lower()
        try:
            text = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            continue
        mesh = _mesh_entries(rel, text)
        if mesh.vendor is not MeshVendor.UNKNOWN:
            meshes.append(mesh)
        if suffix in _CONF or rel.endswith("nginx.conf"):
            model = _parse_nginx(rel, text)
            if model.routes or model.upstreams:
                gateways.append(model)
            continue
        if suffix not in _YAML:
            continue
        docs = _yaml_docs(text)
        if not docs and any(
                m in text.lower() for m in
                ("kong", "envoy", "x-amazon-apigateway", "static_resources")):
            unknowns.append(UnknownFact(
                subject=rel,
                missing="parseable gateway config",
                resolution="file has gateway markers but invalid YAML"))
            continue
        for doc in docs:
            dialect = _detect_yaml_dialect(doc)
            if dialect is GatewayDialect.KONG:
                gateways.append(_parse_kong(rel, doc))
            elif dialect is GatewayDialect.ENVOY:
                gateways.append(_parse_envoy(rel, doc))
            elif dialect is GatewayDialect.AWS_API_GATEWAY:
                gateways.append(_parse_aws(rel, doc))
            elif "kong" in text[:200].lower() or "envoy" in text[:200].lower():
                unknowns.append(UnknownFact(
                    subject=rel,
                    missing="recognized gateway dialect structure",
                    resolution="supported: kong declarative, envoy, "
                               "aws-api-gateway export, nginx conf"))
            break  # only the first doc decides dialect per file
    return tuple(gateways), tuple(meshes), tuple(unknowns)


def gateway_route_map(model: GatewayModel) -> dict[str, str]:
    """Route map for twin/drift consumers — path → upstream."""
    return {r.path: r.upstream or "" for r in model.routes}
