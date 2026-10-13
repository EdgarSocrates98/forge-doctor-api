"""§110-§115, §190-§191 fleet report assembly over a workspace.

Every answer is a `FleetEntry` carrying evidence; missing inputs produce
`UnknownFact`s on the question or field — partial workspaces are never
silently dropped (§203 aggregation discipline).
"""

from __future__ import annotations

import contextlib
from datetime import date
from typing import TYPE_CHECKING

from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.checks.client.engine import _path_matches
from forge_doctor_api.core.context import ContextError, ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    Finding,
    UnknownFact,
)
from forge_doctor_api.fleet.collect import (
    MemberData,
    collect_all,
    member_context,
    operations,
    sanitize_host,
)
from forge_doctor_api.fleet.model import (
    ComplexitySignal,
    DeprecationReadiness,
    FleetEntry,
    FleetExternalApi,
    FleetHealth,
    FleetQuestion,
    FleetReport,
    PortfolioMember,
    QualityDimension,
)
from forge_doctor_api.workspace.model import MemberRole, Workspace

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forge_doctor_api.analyzers.openapi.model import OpenApiOperation
    from forge_doctor_api.analyzers.runtime.history import RequestHistory

_QUESTIONS = {
    "public_apis": "Which services expose public APIs?",
    "unowned_apis": "Which APIs have no owners?",
    "unauthenticated_operations": "Which operations have no auth evidence?",
    "deprecated_versions": "Which services use deprecated API versions?",
    "regressing_endpoints": "Which endpoints repeatedly regress?",
    "shared_external_apis": "Which services depend on the same external API?",
}


def _ev(source: str, summary: str, line: int | None = None) -> tuple[Evidence, ...]:
    return (Evidence(kind=EvidenceKind.STATIC, source=source, summary=summary, line=line),)


def _question(
    key: str,
    entries: Sequence[FleetEntry],
    unknowns: Sequence[UnknownFact] = (),
) -> FleetQuestion:
    return FleetQuestion(
        key=key, question=_QUESTIONS[key], entries=tuple(entries),
        unknowns=tuple(unknowns),
    )


def _op_ev(repo: str, op: OpenApiOperation) -> tuple[Evidence, ...]:
    return _ev(f"{repo}:{op.location.path}", f"{op.method} {op.path}",
               op.location.line)


def _public_apis(data: dict[str, MemberData]) -> FleetQuestion:
    entries = []
    for name, d in sorted(data.items()):
        ops = operations(d)
        if not ops:
            continue
        public = [o for o in ops if not o.has_security]
        if public:
            entries.append(FleetEntry(
                repo=name, subject=name,
                detail=(
                    f"{len(public)}/{len(ops)} operations declare no security "
                    "requirement"
                ),
                evidence=tuple(ev for o in public[:3] for ev in _op_ev(name, o)),
            ))
    return _question("public_apis", entries)


def _unowned(data: dict[str, MemberData]) -> FleetQuestion:
    entries = []
    for name, d in sorted(data.items()):
        if d.openapi is None or not d.openapi.operations:
            continue
        owner = next((o.owner for o in d.ownership if o.owner), None)
        if owner is None:
            entries.append(FleetEntry(
                repo=name, subject=name,
                detail="no owner resolved from declared sources (§186)",
                evidence=_ev(name, "ownership resolution exhausted"),
            ))
    return _question("unowned_apis", entries)


def _unauthenticated(data: dict[str, MemberData]) -> FleetQuestion:
    entries = [
        FleetEntry(
            repo=name,
            subject=f"{o.method} {o.path}",
            detail="operation declares no security requirement",
            evidence=_op_ev(name, o),
        )
        for name, d in sorted(data.items())
        for o in operations(d)
        if not o.has_security
    ]
    return _question("unauthenticated_operations", entries)


def _deprecated(data: dict[str, MemberData]) -> FleetQuestion:
    entries = []
    for name, d in sorted(data.items()):
        if d.version is not None and d.version.deprecation.deprecated:
            dep = d.version.deprecation
            detail = "API marked deprecated"
            if dep.deprecation_date:
                detail += f" since {dep.deprecation_date}"
            if dep.sunset_date:
                detail += f", sunset {dep.sunset_date}"
            entries.append(FleetEntry(
                repo=name, subject=name, detail=detail,
                evidence=dep.evidence or _ev(name, "deprecation marker"),
            ))
    return _question("deprecated_versions", entries)


def _regressing(
    regressions: Mapping[str, Sequence[str]] | None,
) -> FleetQuestion:
    if regressions is None:
        return _question("regressing_endpoints", (), unknowns=(
            UnknownFact(
                subject="(workspace)",
                missing="runtime regression evidence",
                resolution="provide runtime findings/artifacts per member repo",
            ),
        ))
    entries = []
    for repo, subjects in sorted(regressions.items()):
        counts: dict[str, int] = {}
        for s in subjects:
            counts[s] = counts.get(s, 0) + 1
        for subject, n in sorted(counts.items()):
            if n > 1:
                entries.append(FleetEntry(
                    repo=repo, subject=subject,
                    detail=f"regressed in {n} windows",
                    evidence=_ev(repo, "runtime regression evidence"),
                ))
    return _question("regressing_endpoints", entries)


def _shared_external(
    externals: list[FleetExternalApi],
) -> FleetQuestion:
    by_host: dict[str, set[str]] = {}
    for ext in externals:
        by_host.setdefault(ext.host, set()).add(ext.repo)
    entries = [
        FleetEntry(
            repo=sorted(repos)[0], subject=host,
            detail=f"shared by {len(repos)} repos: {', '.join(sorted(repos))}",
            evidence=_ev(",".join(sorted(repos)), "external host dependency"),
        )
        for host, repos in sorted(by_host.items())
        if len(repos) > 1
    ]
    return _question("shared_external_apis", entries)


def _portfolio(data: dict[str, MemberData]) -> tuple[PortfolioMember, ...]:
    out = []
    for name, d in sorted(data.items()):
        apis = len(d.openapi.documents) if d.openapi is not None else 0
        out.append(PortfolioMember(
            repo=name,
            role=d.member.role.value,
            styles=d.styles,
            apis=apis,
            operations=len(operations(d)),
            gateways=len(d.gateway_routes or {}),
            external_apis=(
                len(d.security.external_apis) if d.security is not None else 0
            ),
            owner=next((o.owner for o in d.ownership if o.owner), None),
        ))
    return tuple(out)


def _complexity(
    data: dict[str, MemberData], externals: list[FleetExternalApi],
) -> tuple[ComplexitySignal, ...]:
    out: list[ComplexitySignal] = []

    for name, d in sorted(data.items()):
        api_styles = [s for s in d.styles if s != "gateway"]
        if len(api_styles) >= 2:
            out.append(ComplexitySignal(
                kind="multi_protocol",
                detail=f"{name} exposes APIs over {len(api_styles)} styles: "
                       f"{', '.join(api_styles)}",
                subjects=(name,),
                evidence=_ev(name, "detected styles " + ",".join(api_styles)),
            ))

    by_host: dict[str, set[str]] = {}
    for ext in externals:
        by_host.setdefault(ext.host, set()).add(ext.repo)
    for host, repos in sorted(by_host.items()):
        if len(repos) >= 2:
            out.append(ComplexitySignal(
                kind="shared_external_dependency",
                detail=f"external host {host} wrapped by {len(repos)} repos: "
                       f"{', '.join(sorted(repos))}",
                subjects=(host, *sorted(repos)),
                evidence=_ev(host, f"{len(repos)} consumers"),
            ))

    route_owners: dict[str, set[str]] = {}
    for name, d in sorted(data.items()):
        for route in (d.gateway_routes or {}):
            route_owners.setdefault(route.rstrip("/"), set()).add(name)
    for route, repos in sorted(route_owners.items()):
        if len(repos) >= 2:
            out.append(ComplexitySignal(
                kind="gateway_chain",
                detail=f"route {route} fronted by {len(repos)} gateways: "
                       f"{', '.join(sorted(repos))}",
                subjects=(route, *sorted(repos)),
                evidence=_ev(",".join(sorted(repos)), f"route {route}"),
            ))

    auth_types = sorted({
        s.type.value
        for d in data.values() if d.security is not None
        for s in d.security.auth_schemes
        if s.type.value != "unknown"
    })
    if len(auth_types) >= 2:
        out.append(ComplexitySignal(
            kind="multiple_auth_models",
            detail=f"{len(auth_types)} distinct auth scheme types across "
                   f"workspace: {', '.join(auth_types)}",
            subjects=tuple(auth_types),
            evidence=_ev("(workspace)", "auth scheme inventory"),
        ))
    return tuple(out)


def _deprecation_readiness(
    context: ProjectContext,
    data: dict[str, MemberData],
    clients_by_repo: Mapping[str, ApiClientModel],
    runtime: Mapping[str, RequestHistory] | None,
) -> tuple[DeprecationReadiness, ...]:
    """§114 per deprecated API: clients, traffic, replacement, age."""
    out: list[DeprecationReadiness] = []
    today: date | None = None
    with contextlib.suppress(ContextError):
        today = context.now().date()
    for name, d in sorted(data.items()):
        if d.version is None or not d.version.deprecation.deprecated:
            continue
        dep = d.version.deprecation
        unknowns: list[UnknownFact] = []
        deprecated_ops = [o for o in operations(d) if o.deprecated]
        targets = deprecated_ops or operations(d)  # api-level: all ops
        paths = [o.path for o in targets]

        if not clients_by_repo:
            remaining = None
            remaining_subjects: tuple[str, ...] = ()
            unknowns.append(UnknownFact(
                subject=name, missing="client call evidence",
                resolution="add client member repos to the workspace manifest",
            ))
        else:
            sites = [
                s for repo, model in clients_by_repo.items()
                for s in model.call_sites
                if s.path is not None
                and any(_path_matches(p, s.path) for p in paths)
            ]
            remaining = len({s.client for s in sites})
            remaining_subjects = tuple(sorted({s.client for s in sites}))

        traffic: int | None = None
        if runtime is None:
            unknowns.append(UnknownFact(
                subject=name, missing="runtime traffic evidence",
                resolution="ingest runtime artifacts for observed traffic",
            ))
        else:
            hist = runtime.get(name)
            if hist is None:
                unknowns.append(UnknownFact(
                    subject=name, missing="runtime traffic evidence",
                    resolution="ingest runtime artifacts for this repo",
                ))
            else:
                target_ids = {o.identity for o in targets}
                traffic = sum(
                    1 for r in hist.query()
                    if r.operation in target_ids
                    or any(
                        _path_matches(p, "/" + r.operation.lstrip("/"))
                        for p in paths
                    )
                )

        age: int | None = None
        if dep.deprecation_date and today is not None:
            try:
                age = (today - date.fromisoformat(dep.deprecation_date[:10])).days
            except ValueError:
                unknowns.append(UnknownFact(
                    subject=name, missing="parseable deprecation date",
                    resolution=f"fix x-deprecation-date {dep.deprecation_date!r}",
                ))
        elif dep.deprecation_date is None:
            unknowns.append(UnknownFact(
                subject=name, missing="deprecation date",
                resolution="declare x-deprecation-date",
            ))

        out.append(DeprecationReadiness(
            repo=name, subject=name,
            remaining_clients=remaining,
            remaining_client_subjects=remaining_subjects,
            observed_traffic=traffic,
            replacement=dep.replacement,
            contract_age_days=age,
            sunset_date=dep.sunset_date,
            unknowns=tuple(unknowns),
        ))
    return tuple(sorted(out, key=lambda r: (r.repo, r.subject)))


def _external_apis(data: dict[str, MemberData]) -> list[FleetExternalApi]:
    """§115-§116 external dependencies; hosts sanitized; signals candidates."""
    out: list[FleetExternalApi] = []
    for name, d in sorted(data.items()):
        if d.security is None:
            continue
        for ext in d.security.external_apis:
            signals: list[str] = []
            if ext.timeout_ms is None:
                signals.append("no timeout configured [candidate]")
            if ext.has_retry is False:
                signals.append("no retry policy configured [candidate]")
            if ext.has_auth is False:
                signals.append("no auth evidence on external calls [candidate]")
            out.append(FleetExternalApi(
                repo=name,
                host=sanitize_host(ext.host),
                operations=ext.operations,
                timeout_ms=ext.timeout_ms,
                has_retry=ext.has_retry,
                has_auth=ext.has_auth,
                owner=ext.owner or next(
                    (o.owner for o in d.ownership if o.owner), None),
                criticality=ext.criticality,
                signals=tuple(signals),
                evidence=ext.evidence,
            ))
    return out


def _quality(data: dict[str, MemberData]) -> tuple[QualityDimension, ...]:
    """§190 per-dimension evidence; no composite score."""
    dims: list[QualityDimension] = []
    for name, d in sorted(data.items()):
        ops = operations(d)
        if not ops:
            continue
        with_oid = sum(1 for o in ops if o.operation_id)
        dims.append(QualityDimension(
            name="contract completeness", repo=name,
            value=f"{with_oid}/{len(ops)} operations have operationId",
            evidence=_ev(name, "operationId coverage"),
        ))
        secured = sum(1 for o in ops if o.has_security)
        dims.append(QualityDimension(
            name="security posture evidence", repo=name,
            value=f"{secured}/{len(ops)} operations declare security",
            evidence=_ev(name, "security requirement coverage"),
        ))
        documented = sum(1 for o in ops if o.description or o.summary)
        dims.append(QualityDimension(
            name="documentation", repo=name,
            value=f"{documented}/{len(ops)} operations documented",
            evidence=_ev(name, "description/summary coverage"),
        ))
        owner = next((o.owner for o in d.ownership if o.owner), None)
        dims.append(QualityDimension(
            name="ownership", repo=name,
            value=f"owner: {owner}" if owner else "unknown",
            evidence=_ev(name, "§186 resolution"),
            unknowns=() if owner else (UnknownFact(
                subject=name, missing="owner",
                resolution="declare an owner in any §186 source",
            ),),
        ))
        if d.reliability is not None:
            rel = d.reliability
            dims.append(QualityDimension(
                name="reliability", repo=name,
                value=f"{len(rel.timeouts)} timeouts, {len(rel.retry_policies)} "
                      f"retries, {len(rel.objectives)} SLOs declared",
                evidence=_ev(name, "reliability config coverage"),
            ))
    return tuple(dims)


_HEALTH_PREFIXES = {
    "breaking_changes": ("COMPAT", "DRIFT"),
    "reliability_gaps": ("RELAPI",),
    "security_candidates": ("APISEC",),
    "runtime_regressions": ("APIPERF", "OBSAPI"),
}


def fleet_health_counts(findings: tuple[Finding, ...]) -> FleetHealth:
    """§191 health as counts over a findings set — no composite score."""
    counts = {k: 0 for k in _HEALTH_PREFIXES}
    unknowns = 0
    for f in findings:
        for key, prefixes in _HEALTH_PREFIXES.items():
            if f.id.startswith(prefixes):
                counts[key] += 1
                break
        unknowns += len(f.unknowns)
    return FleetHealth(**counts, unknowns=unknowns)


def build_fleet_report(
    context: ProjectContext,
    workspace: Workspace,
    *,
    regressions: Mapping[str, Sequence[str]] | None = None,
    runtime: Mapping[str, RequestHistory] | None = None,
    findings: tuple[Finding, ...] = (),
) -> FleetReport:
    """Aggregate all member repos into a §110-§115 fleet report."""
    data = collect_all(context, workspace)

    clients_by_repo: dict[str, ApiClientModel] = {}
    for name, d in data.items():
        if d.member.role in (MemberRole.CLIENT, MemberRole.MIXED):
            ctx = member_context(context, d.member)
            clients_by_repo[name] = scan_clients(ctx, d.files)

    externals = _external_apis(data)
    questions = (
        _public_apis(data),
        _unowned(data),
        _unauthenticated(data),
        _deprecated(data),
        _regressing(regressions),
        _shared_external(externals),
    )
    unknowns = list(workspace.unknowns)
    for m in workspace.members:
        if not m.present:
            unknowns.append(UnknownFact(
                subject=m.name,
                missing="member repo checkout",
                resolution="clone the member repo at its declared path",
            ))

    return FleetReport(
        workspace=workspace.name,
        members_present=tuple(sorted(data)),
        members_missing=tuple(
            m.name for m in workspace.members if not m.present
        ),
        questions=questions,
        portfolio=_portfolio(data),
        complexity=_complexity(data, externals),
        deprecations=_deprecation_readiness(context, data, clients_by_repo, runtime),
        external_apis=tuple(externals),
        quality=_quality(data),
        unknowns=tuple(unknowns),
    )
