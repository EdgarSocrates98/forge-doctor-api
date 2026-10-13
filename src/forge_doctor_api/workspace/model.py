"""§108-§109 multi-repo workspace models.

A `Workspace` is a declared set of member repos — membership comes only
from `forge-doctor-api.workspace.yaml`; nothing is discovered by walking
the filesystem. Roles are declared or UNKNOWN, never inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Evidence, Model, UnknownFact


class MemberRole(StrEnum):
    """Declared repo role (§108). UNKNOWN when the manifest omits it."""

    SERVICE = "service"
    CLIENT = "client"
    GATEWAY = "gateway"
    CONTRACTS = "contracts"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class EdgeKind(StrEnum):
    """Cross-repo link kinds. Direction: dependent -> dependency."""

    CLIENT_CALLS = "client_calls"  # client repo -> service repo operation
    CONTRACT_IMPLEMENTS = "contract_implements"  # service repo -> contracts repo
    GATEWAY_ROUTES = "gateway_routes"  # gateway repo -> service repo
    SDK_CONSUMED_BY = "sdk_consumed_by"  # consumer repo -> provider repo


@dataclass(frozen=True, kw_only=True)
class WorkspaceMember(Model):
    """One declared member repo.

    `provides`: importable package/API names this repo exposes, declared in
    the manifest — the only evidence linking consumers to providers.
    `present`: False when the declared path does not exist on disk.
    """

    name: str
    path: str
    role: MemberRole
    provides: tuple[str, ...] = ()
    present: bool = True


@dataclass(frozen=True, kw_only=True)
class CrossRepoEdge(Model):
    """One evidenced link between two member repos.

    `from_repo` is the dependent, `to_repo` the dependency; `subject`
    identifies the linked artifact (e.g. `GET /charges`, a route prefix,
    an import statement) so every edge is auditable.
    """

    kind: EdgeKind
    from_repo: str
    to_repo: str
    subject: str
    detail: str = ""
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Workspace(Model):
    """§108 workspace manifest materialized."""

    name: str
    members: tuple[WorkspaceMember, ...] = ()
    issues: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ChainHop(Model):
    """§109 one hop of a cross-repo contract chain (dependent -> dependency)."""

    from_repo: str
    to_repo: str
    edge_kind: EdgeKind
    subjects: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CrossRepoChain(Model):
    """§109 chain such as consumer -> sdk -> service, each hop evidenced."""

    repos: tuple[str, ...]
    hops: tuple[ChainHop, ...]


@dataclass(frozen=True, kw_only=True)
class WorkspaceScan(Model):
    """Per-repo scan assembly + resolved cross-repo edges and chains."""

    workspace: Workspace
    edges: tuple[CrossRepoEdge, ...] = ()
    chains: tuple[CrossRepoChain, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
