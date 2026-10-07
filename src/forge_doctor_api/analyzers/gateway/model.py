"""§72 GatewayModel + §73 ServiceMeshModel — declared config, not capabilities.

These models capture what a committed gateway/mesh config *declares*.
Platform *capabilities* live in knowledge packs (§130); this is the
observed side — every field is an evidence-bearing record or absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)


class GatewayDialect(StrEnum):
    KONG = "kong"
    ENVOY = "envoy"
    AWS_API_GATEWAY = "aws-api-gateway"
    NGINX = "nginx"
    TRAEFIK = "traefik"


@dataclass(frozen=True, kw_only=True)
class GatewayRoute(Model):
    """A declared route: path prefix → upstream target."""

    path: str
    upstream: str | None
    location: SourceLocation
    service: str | None = None  # resolved target; None => unresolved


@dataclass(frozen=True, kw_only=True)
class GatewayUpstream(Model):
    """A declared upstream/cluster/service target."""

    name: str
    host: str | None           # literal host/url when declared
    location: SourceLocation


class PolicyKind(StrEnum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    CORS = "cors"
    OTHER = "other"


@dataclass(frozen=True, kw_only=True)
class GatewayPolicy(Model):
    """A declared policy binding with literal params only."""

    kind: PolicyKind
    name: str
    params: tuple[tuple[str, str], ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class MeshEdge(Model):
    """A declared traffic-policy edge — never name-inferred."""

    source: str                # e.g. "VirtualService/reviews"
    target: str                # declared destination host/subset
    kind: str                  # "route" | "subset" | "profile"
    via: str                   # declaring field, e.g. "destination.host"
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ConfigEntry(Model):
    """A named config declaration (plugin/policy/auth/rate-limit/etc.)."""

    name: str
    detail: str
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GatewayModel(Model):
    """§72 — the declared gateway surface for one config file."""

    dialect: GatewayDialect
    source: SourceLocation
    routes: tuple[GatewayRoute, ...] = ()
    upstreams: tuple[ConfigEntry, ...] = ()
    plugins: tuple[ConfigEntry, ...] = ()
    auth: tuple[ConfigEntry, ...] = ()
    rate_limits: tuple[ConfigEntry, ...] = ()
    retries: tuple[ConfigEntry, ...] = ()
    timeouts: tuple[ConfigEntry, ...] = ()
    transformations: tuple[ConfigEntry, ...] = ()
    policies: tuple[ConfigEntry, ...] = ()
    upstream_targets: tuple[GatewayUpstream, ...] = ()
    policy_entries: tuple[GatewayPolicy, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


class MeshVendor(StrEnum):
    ISTIO = "istio"
    ENVOY = "envoy"
    LINKERD = "linkerd"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class ServiceMeshModel(Model):
    """§73 — detected mesh evidence: routing/retry/timeout/cb/mTLS/split.

    Marker-driven only: absent markers → empty model, no findings.
    """

    vendor: MeshVendor = MeshVendor.UNKNOWN
    routing: tuple[ConfigEntry, ...] = ()
    retries: tuple[ConfigEntry, ...] = ()
    timeouts: tuple[ConfigEntry, ...] = ()
    circuit_breakers: tuple[ConfigEntry, ...] = ()
    mtls: tuple[ConfigEntry, ...] = ()
    traffic_splits: tuple[ConfigEntry, ...] = ()
    edges: tuple[MeshEdge, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
