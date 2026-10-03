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


@dataclass(frozen=True, kw_only=True)
class GatewayRoute(Model):
    """A declared route: path prefix → upstream target."""

    path: str
    upstream: str | None
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
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
