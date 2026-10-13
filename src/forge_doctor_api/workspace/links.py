"""§108-§109 per-repo assembly + cross-repo edge resolution.

Each member repo is scanned with the single-repo analyzers
(`load_openapi_project`, `scan_clients`, `gateway_routes`) under its own
`ProjectContext`; links are then resolved across member boundaries. Every
edge names both repos and cites evidence on both sides — nothing is
inferred from layout or naming conventions.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OperationSource,
)
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.client.engine import _path_matches
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind, UnknownFact
from forge_doctor_api.security.scan import normalize_route_path
from forge_doctor_api.twin.drift import gateway_routes
from forge_doctor_api.workspace.model import (
    ChainHop,
    CrossRepoChain,
    CrossRepoEdge,
    EdgeKind,
    MemberRole,
    Workspace,
    WorkspaceMember,
    WorkspaceScan,
)

_SERVICE_ROLES = {MemberRole.SERVICE, MemberRole.MIXED}
_CONTRACT_ROLES = {MemberRole.CONTRACTS, MemberRole.MIXED}
_CLIENT_ROLES = {MemberRole.CLIENT, MemberRole.MIXED}
_GATEWAY_ROLES = {MemberRole.GATEWAY, MemberRole.MIXED}
_CONSUMER_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_PY_IMPORT = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)")
_JS_IMPORT = re.compile(r"""(?:from\s+|require\()\s*['"]([^'"]+)['"]""")


def _ev(source: str, summary: str, line: int | None = None) -> tuple[Evidence, ...]:
    return (Evidence(kind=EvidenceKind.STATIC, source=source, summary=summary, line=line),)


def _member_context(context: ProjectContext, member: WorkspaceMember) -> ProjectContext:
    return ProjectContext.from_root(context.resolve(member.path), clock=context.clock)


def _norm(name: str) -> str:
    """`payments-sdk` == `payments_sdk` for import matching."""
    return re.sub(r"[-_.]+", "", name).lower()


def _imported_modules(source: str, is_python: bool) -> list[str]:
    """First module/package segment of each import/require statement."""
    pattern = _PY_IMPORT if is_python else _JS_IMPORT
    out: list[str] = []
    for line in source.splitlines():
        m = pattern.search(line)
        if not m:
            continue
        mod = m.group(1)
        if is_python:
            out.append(mod.split(".", 1)[0])
        else:
            parts = mod.lstrip("@").split("/")
            keep = 2 if mod.startswith("@") and len(parts) > 1 else 1
            out.append("/".join(parts[:keep]))
    return out


def _contract_edges(
    members: list[WorkspaceMember],
    ops: dict[str, list[OpenApiOperation]],
) -> list[CrossRepoEdge]:
    """contracts repo op shared verbatim with a service repo -> implements edge."""
    out: list[CrossRepoEdge] = []
    services = [m for m in members if m.role in _SERVICE_ROLES and m.name in ops]
    contracts = [m for m in members if m.role in _CONTRACT_ROLES and m.name in ops]
    for svc in services:
        svc_keys = {
            (op.method.upper(), normalize_route_path(op.path)): op
            for op in ops[svc.name]
        }
        for con in contracts:
            if con.name == svc.name:
                continue
            for op in ops[con.name]:
                key = (op.method.upper(), normalize_route_path(op.path))
                impl = svc_keys.get(key)
                if impl is None:
                    continue
                out.append(CrossRepoEdge(
                    kind=EdgeKind.CONTRACT_IMPLEMENTS,
                    from_repo=svc.name, to_repo=con.name,
                    subject=f"{key[0]} {key[1]}",
                    detail=(
                        f"{svc.name} implements contract op declared in {con.name}"
                    ),
                    evidence=(
                        _ev(f"{svc.name}:{impl.location.path}", "implementation",
                            impl.location.line)
                        + _ev(f"{con.name}:{op.location.path}", "contract",
                              op.location.line)
                    ),
                ))
    return out


def _client_call_edges(
    members: list[WorkspaceMember],
    clients: dict[str, ApiClientModel],
    ops: dict[str, list[OpenApiOperation]],
) -> list[CrossRepoEdge]:
    """client repo call site matching a service repo op -> client_calls edge."""
    out: list[CrossRepoEdge] = []
    services = [m for m in members if m.role in _SERVICE_ROLES and m.name in ops]
    for member in members:
        if member.role not in _CLIENT_ROLES or member.name not in clients:
            continue
        for site in clients[member.name].call_sites:
            if site.path is None:
                continue
            for svc in services:
                if svc.name == member.name:
                    continue
                for op in ops[svc.name]:
                    if not _path_matches(op.path, site.path):
                        continue
                    if site.method is not None and site.method != op.method:
                        continue
                    out.append(CrossRepoEdge(
                        kind=EdgeKind.CLIENT_CALLS,
                        from_repo=member.name, to_repo=svc.name,
                        subject=f"{op.method} {normalize_route_path(op.path)}",
                        detail=(
                            f"call site {site.location.path}:"
                            f"{site.location.line or 0} in {member.name} calls "
                            f"{svc.name}"
                        ),
                        evidence=(
                            _ev(f"{member.name}:{site.location.path}",
                                f"{site.library} call", site.location.line)
                            + _ev(f"{svc.name}:{op.location.path}",
                                  "operation", op.location.line)
                        ),
                    ))
    return out


def _gateway_edges(
    members: list[WorkspaceMember],
    routes: dict[str, dict[str, str]],
    ops: dict[str, list[OpenApiOperation]],
) -> tuple[list[CrossRepoEdge], list[UnknownFact]]:
    """gateway route prefix matching a service repo op -> gateway_routes edge."""
    out: list[CrossRepoEdge] = []
    unknowns: list[UnknownFact] = []
    services = [m for m in members if m.role in _SERVICE_ROLES and m.name in ops]
    for member in members:
        if member.role not in _GATEWAY_ROLES or member.name not in routes:
            continue
        for route, src in sorted(routes[member.name].items()):
            norm = normalize_route_path(route)
            matched = False
            for svc in services:
                if svc.name == member.name:
                    continue
                for op in ops[svc.name]:
                    op_path = normalize_route_path(op.path)
                    if norm != op_path and not op_path.startswith(norm.rstrip("/") + "/"):
                        continue
                    matched = True
                    out.append(CrossRepoEdge(
                        kind=EdgeKind.GATEWAY_ROUTES,
                        from_repo=member.name, to_repo=svc.name,
                        subject=f"{op.method} {op_path}",
                        detail=(
                            f"gateway route {route} in {member.name} fronts "
                            f"{svc.name}"
                        ),
                        evidence=(
                            _ev(f"{member.name}:{src}", "gateway route")
                            + _ev(f"{svc.name}:{op.location.path}",
                                  "operation", op.location.line)
                        ),
                    ))
            if not matched and norm != "/":
                unknowns.append(UnknownFact(
                    subject=route,
                    missing=f"service repo fronted by gateway route in {member.name}",
                    resolution="declare the upstream service repo or the route's contract",
                ))
    return out, unknowns


def _sdk_edges(
    members: list[WorkspaceMember],
    contexts: dict[str, ProjectContext],
) -> list[CrossRepoEdge]:
    """consumer repo importing a member's declared `provides` name -> edge."""
    providers = {m.name: m for m in members if m.provides}
    out: list[CrossRepoEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for member in members:
        ctx = contexts.get(member.name)
        if ctx is None:
            continue
        for rel in ctx.iter_files():
            if Path(rel).suffix.lower() not in _CONSUMER_SUFFIXES:
                continue
            try:
                source = ctx.read_text(rel)
            except (OSError, UnicodeDecodeError):
                continue
            is_py = rel.endswith(".py")
            for lineno, line in enumerate(source.splitlines(), 1):
                mods = _imported_modules(line, is_py)
                for prov in providers.values():
                    if prov.name == member.name:
                        continue
                    hit = next(
                        (mod for mod in mods if any(
                            _norm(mod) == _norm(p) for p in prov.provides)),
                        None,
                    )
                    key = (member.name, prov.name, rel)
                    if hit is None or key in seen:
                        continue
                    seen.add(key)
                    out.append(CrossRepoEdge(
                        kind=EdgeKind.SDK_CONSUMED_BY,
                        from_repo=member.name, to_repo=prov.name,
                        subject=f"import {hit}",
                        detail=f"{member.name} consumes {prov.name} via {rel}:{lineno}",
                        evidence=_ev(f"{member.name}:{rel}", "import", lineno),
                    ))
    return out


def resolve_chains(edges: tuple[CrossRepoEdge, ...]) -> tuple[CrossRepoChain, ...]:
    """§109 all simple repo chains of length >= 2 hops (dependent -> dependency)."""
    by_pair: dict[tuple[str, str], list[CrossRepoEdge]] = {}
    for e in edges:
        by_pair.setdefault((e.from_repo, e.to_repo), []).append(e)
    adjacency: dict[str, list[str]] = {}
    for (frm, to) in by_pair:
        adjacency.setdefault(frm, []).append(to)

    chains: list[CrossRepoChain] = []

    def walk(repo: str, path: list[str]) -> None:
        if len(path) >= 3:
            hops = []
            for i in range(len(path) - 1):
                pair_edges = by_pair[(path[i], path[i + 1])]
                hops.append(ChainHop(
                    from_repo=path[i], to_repo=path[i + 1],
                    edge_kind=pair_edges[0].kind,
                    subjects=tuple(sorted({e.subject for e in pair_edges})),
                    evidence=tuple(ev for e in pair_edges for ev in e.evidence),
                ))
            chains.append(CrossRepoChain(repos=tuple(path), hops=tuple(hops)))
        for nxt in sorted(adjacency.get(repo, [])):
            if nxt not in path:
                walk(nxt, [*path, nxt])

    for start in sorted(adjacency):
        walk(start, [start])
    chains.sort(key=lambda c: c.repos)
    return tuple(chains)


def scan_workspace(context: ProjectContext, workspace: Workspace) -> WorkspaceScan:
    """Scan each member repo with single-repo analyzers, then resolve links."""
    members = [m for m in workspace.members]
    contexts: dict[str, ProjectContext] = {}
    for m in members:
        if m.present:
            contexts[m.name] = _member_context(context, m)

    ops: dict[str, list[OpenApiOperation]] = {}
    clients: dict[str, ApiClientModel] = {}
    routes: dict[str, dict[str, str]] = {}
    for m in members:
        ctx = contexts.get(m.name)
        if ctx is None:
            continue
        files = list(ctx.iter_files())
        if m.role in _SERVICE_ROLES | _CONTRACT_ROLES:
            ops[m.name] = [
                op for op in load_openapi_project(ctx).operations
                if op.source is OperationSource.PATH
            ]
        if m.role in _CLIENT_ROLES:
            clients[m.name] = scan_clients(ctx, files)
        if m.role in _GATEWAY_ROLES:
            routes[m.name] = gateway_routes(ctx, files)

    edges: list[CrossRepoEdge] = []
    edges += _contract_edges(members, ops)
    edges += _client_call_edges(members, clients, ops)
    gw_edges, gw_unknowns = _gateway_edges(members, routes, ops)
    edges += gw_edges
    edges += _sdk_edges(members, contexts)
    edges.sort(key=lambda e: (e.kind.value, e.from_repo, e.to_repo, e.subject))

    return WorkspaceScan(
        workspace=workspace,
        edges=tuple(edges),
        chains=resolve_chains(tuple(edges)),
        unknowns=tuple(gw_unknowns) + tuple(workspace.unknowns),
    )
