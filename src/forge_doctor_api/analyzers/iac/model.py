"""§74-76 infrastructure models — Kubernetes manifests + IaC evidence.

Evidence extraction from committed manifests only: no cluster API, no
HCL evaluation, no live state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Model, SourceLocation, UnknownFact


class K8sKind(StrEnum):
    SERVICE = "Service"
    INGRESS = "Ingress"
    GATEWAY = "Gateway"          # gateway.networking.k8s.io
    HTTPROUTE = "HTTPRoute"      # gateway.networking.k8s.io
    DEPLOYMENT = "Deployment"
    HPA = "HorizontalPodAutoscaler"
    CONFIGMAP = "ConfigMap"
    OTHER = "Other"


@dataclass(frozen=True, kw_only=True)
class KubernetesResource(Model):
    """One manifest object (§75)."""

    kind: K8sKind
    api_version: str
    name: str
    namespace: str | None = None
    labels: tuple[tuple[str, str], ...] = ()
    selectors: tuple[tuple[str, str], ...] = ()
    backends: tuple[str, ...] = ()   # explicit serviceName/name references
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ChainLink(Model):
    """One §76 hop — resolved by declared identifiers only."""

    source: str   # "Kind/name" e.g. "Ingress/web"
    target: str   # "Kind/name" or "api-operations"
    via: str      # "backend" | "selector:<k>=<v>" | "label:<k>=<v>"
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class IacAttr(Model):
    """One literal attribute candidate with evidence location."""

    name: str
    value: str | None          # None + dynamic=True => not a literal
    location: SourceLocation
    dynamic: bool = False


@dataclass(frozen=True, kw_only=True)
class IacResource(Model):
    """One declared IaC resource (Terraform `resource`, Helm chart)."""

    iac_kind: str        # "terraform" | "helm" | "cloudformation"
    type_name: str       # resource type or chart name
    name: str
    location: SourceLocation
    parsed: bool = True          # False => recorded-not-parsed (CFN)
    attrs: tuple[IacAttr, ...] = ()
    existence_known: bool = True  # False under dynamic count/for_each


@dataclass(frozen=True, kw_only=True)
class InfraModel(Model):
    """Project-level §74-76 model."""

    kubernetes: tuple[KubernetesResource, ...] = ()
    chains: tuple[ChainLink, ...] = ()
    iac: tuple[IacResource, ...] = ()
    issues: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
