"""§109 cross-repo blast radius.

A changed operation in a service repo propagates to repos with
`client_calls`/`gateway_routes` edges on that subject, then transitively
to repos depending on those repos (`sdk_consumed_by`, further client
calls). Repos without evidenced linkage yield an UnknownFact — impact
outside the declared workspace is never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Model, UnknownFact
from forge_doctor_api.security.scan import normalize_route_path
from forge_doctor_api.workspace.model import (
    CrossRepoEdge,
    EdgeKind,
    MemberRole,
    WorkspaceScan,
)


def _norm_subject(subject: str) -> str:
    """`GET /charges/{id}` -> `GET /charges/{}` to match stored edge subjects."""
    parts = subject.split(" ", 1)
    if len(parts) == 2 and parts[1].startswith("/"):
        return f"{parts[0].upper()} {normalize_route_path(parts[1])}"
    return normalize_route_path(subject) if subject.startswith("/") else subject

_SUBJECT_KINDS = {EdgeKind.CLIENT_CALLS, EdgeKind.GATEWAY_ROUTES}


@dataclass(frozen=True, kw_only=True)
class WorkspaceBlastNode(Model):
    """One changed subject: the repo it lives in + impacted dependents."""

    subject: str
    repo: str = ""
    impacted_repos: tuple[str, ...] = ()
    chains: tuple[tuple[str, ...], ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WorkspaceBlastReport(Model):
    nodes: tuple[WorkspaceBlastNode, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


def _dependents(edges: tuple[CrossRepoEdge, ...]) -> dict[str, set[str]]:
    """to_repo -> {from_repo}: when `to_repo` changes, its dependents are hit."""
    out: dict[str, set[str]] = {}
    for e in edges:
        out.setdefault(e.to_repo, set()).add(e.from_repo)
    return out


def workspace_blast_radius(
    scan: WorkspaceScan, subjects: tuple[str, ...]
) -> WorkspaceBlastReport:
    """Impact of changed operation subjects (e.g. `GET /charges`) across repos."""
    dependents = _dependents(scan.edges)
    member_names = {m.name for m in scan.workspace.members}
    nodes: list[WorkspaceBlastNode] = []
    unknowns: list[UnknownFact] = []

    for subject in subjects:
        norm = _norm_subject(subject)
        hits = [
            e for e in scan.edges
            if e.kind in _SUBJECT_KINDS and e.subject == norm
        ]
        origins = {e.to_repo for e in hits}
        if not origins:
            # no consumer edges on this subject — find implementing repos via
            # any matching edge endpoint with a service/mixed role
            impl_roles = {MemberRole.SERVICE, MemberRole.MIXED}
            by_name = {m.name: m for m in scan.workspace.members}
            endpoints = {
                repo
                for e in scan.edges
                if e.subject == norm or norm.endswith(e.subject.split(" ", 1)[-1])
                for repo in (e.from_repo, e.to_repo)
            }
            origins = {
                r for r in endpoints if by_name.get(r) and by_name[r].role in impl_roles
            } or endpoints
        node_unknowns: list[UnknownFact] = []
        if not origins:
            fact = UnknownFact(
                subject=subject,
                missing="repo owning the changed subject",
                resolution="declare the member repo that owns this operation",
            )
            node_unknowns.append(fact)
            unknowns.append(fact)
            nodes.append(WorkspaceBlastNode(subject=subject, unknowns=(fact,)))
            continue

        seed = {e.from_repo for e in hits}  # direct dependents on this subject
        impacted: set[str] = set(seed)
        chains: list[tuple[str, ...]] = [
            (e.from_repo, e.to_repo) for e in hits
        ]
        frontier = list(seed)
        seen = set(frontier) | origins
        while frontier:
            repo = frontier.pop()
            for dep in sorted(dependents.get(repo, ())):
                if dep in seen or dep not in member_names:
                    continue
                seen.add(dep)
                impacted.add(dep)
                frontier.append(dep)
                chains.append((dep, repo))
        if not impacted:
            fact = UnknownFact(
                subject=subject,
                missing="evidenced consumers within the workspace",
                resolution="declare client/consumer member repos or accept "
                "impact beyond the workspace is unknown",
            )
            node_unknowns.append(fact)
            unknowns.append(fact)
        nodes.append(WorkspaceBlastNode(
            subject=subject,
            repo=sorted(origins)[0],
            impacted_repos=tuple(sorted(impacted)),
            chains=tuple(sorted(set(chains))),
            unknowns=tuple(node_unknowns),
        ))
    nodes.sort(key=lambda n: (n.repo, n.subject))
    return WorkspaceBlastReport(nodes=tuple(nodes), unknowns=tuple(unknowns))
