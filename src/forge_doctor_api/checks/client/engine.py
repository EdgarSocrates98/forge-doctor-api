"""Client impact analysis (§17, §68, §183, spec 009).

Consumes a `ContractDiff` (spec 008) plus an `ApiClientModel` and produces:

- `CLIENT001` — confirmed client impact: the change touches a response field
  a consuming call site statically reads (§183 field-level override).
- `CLIENT002` — blast-radius entry: a client consumes the changed operation
  but no field usage evidence proves impact.
- `CLIENT003` — unresolvable call sites (dynamic URLs/methods).

Confirmed impact never upgrades on path-shape alone (§183): only
response-side field reads count as usage evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.analyzers.clients.model import ApiClientModel, ClientCallSite
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel, OperationSource
from forge_doctor_api.checks.client.catalog import BY_ID, ClientCheckSpec
from forge_doctor_api.checks.compat.catalog import ChangeSide, CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    UnknownFact,
    entity_id,
)

_RESPONSE_FIELD_KINDS = frozenset(
    {"response_field_removed", "type_changed_response", "enum_removed"}
)


@dataclass(frozen=True, kw_only=True)
class BlastRadiusEntry(Model):
    """§68 chain: changed operation -> clients -> call sites."""

    operation: str
    method: str
    path: str
    change_kind: str
    classification: CompatibilityClass
    clients: tuple[str, ...] = ()
    call_sites: tuple[str, ...] = ()
    confirmed: bool = False


@dataclass(frozen=True, kw_only=True)
class ImpactReport(Model):
    entries: tuple[BlastRadiusEntry, ...] = ()
    findings: tuple[Finding, ...] = ()


def _path_matches(template: str, concrete: str) -> bool:
    """Contract template `/users/{id}` vs concrete call `/v1/users/123`.

    `{x}` segments match any single segment; leading base-path segments on
    the concrete path are ignored (suffix match).
    """
    t = [s for s in template.split("/") if s]
    c = [s for s in concrete.split("/") if s]
    if not t or len(c) < len(t):
        return False
    c = c[len(c) - len(t):]
    return all(
        (ts.startswith("{") and ts.endswith("}") and bool(cs)) or ts == cs
        for ts, cs in zip(t, c, strict=True)
    )


def _leaf(path: str) -> str:
    """`response[200]:User.items[].email` -> `email`."""
    tail = path.rsplit(".", 1)[-1]
    return tail.rstrip("[]")


def _finding(spec: ClientCheckSpec, description: str, site: ClientCallSite | None,
             entity_ids: tuple[str, ...], unknowns: tuple[UnknownFact, ...] = ()) -> Finding:
    loc = site.location if site else None
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=loc.path,
                summary=description,
                line=loc.line,
            ),
        )
        if loc
        else (),
        entity_ids=entity_ids,
        source_location=loc,
        unknowns=unknowns,
    )


def client_impact(
    diff: ContractDiff,
    clients: ApiClientModel,
    model: OpenApiProjectModel,
) -> ImpactReport:
    """Map breaking/candidate changes onto consuming call sites.

    `model` is the *old* contract (the one clients were written against).
    """
    ops = {
        op.identity: op
        for op in model.operations
        if op.source is OperationSource.PATH
    }
    entries: list[BlastRadiusEntry] = []
    findings: list[Finding] = []

    for change in diff.changes:
        if change.classification is CompatibilityClass.NON_BREAKING:
            continue
        op = ops.get(change.subject)
        if op is None:
            continue
        consumers = [
            s
            for s in clients.call_sites
            if s.path is not None
            and _path_matches(op.path, s.path)
            and (s.method is None or s.method == op.method)
        ]
        if not consumers:
            continue
        field = _leaf(change.path)
        confirmed_sites = (
            [
                s
                for s in consumers
                if change.side is ChangeSide.RESPONSE
                and change.kind in _RESPONSE_FIELD_KINDS
                and field in s.response_fields
            ]
            if change.classification is CompatibilityClass.BREAKING
            else []
        )
        for site in consumers:
            confirmed = site in confirmed_sites
            spec = BY_ID["CLIENT001" if confirmed else "CLIENT002"]
            usage = (
                f"; client reads field {field!r}"
                if confirmed
                else "; no field-level usage evidence for the changed element"
            )
            findings.append(
                _finding(
                    spec,
                    (
                        f"{site.client}: {site.library} {site.method or '?'} {site.url} "
                        f"consumes {op.identity}; change {change.kind} "
                        f"({change.classification.value}){usage}"
                    ),
                    site,
                    (
                        entity_id("client", "source", site.client),
                        change.subject,
                    ),
                )
            )
        entries.append(
            BlastRadiusEntry(
                operation=change.subject,
                method=op.method,
                path=op.path,
                change_kind=change.kind,
                classification=change.classification,
                clients=tuple(sorted({s.client for s in consumers})),
                call_sites=tuple(
                    sorted(f"{s.location.path}:{s.location.line}" for s in consumers)
                ),
                confirmed=bool(confirmed_sites),
            )
        )

    for unknown in clients.unknowns:
        path = unknown.subject.rpartition(":")[0]
        findings.append(
            _finding(
                BY_ID["CLIENT003"],
                f"{unknown.subject}: client call could not be resolved "
                f"({unknown.missing})",
                None,
                (entity_id("client", "source", path.split("/")[0] or "client"),),
                unknowns=(
                    UnknownFact(
                        subject=unknown.subject,
                        missing=unknown.missing,
                        resolution=unknown.resolution,
                    ),
                ),
            )
        )

    findings.sort(
        key=lambda f: (
            f.id,
            f.source_location.path if f.source_location else "",
            f.description,
        )
    )
    return ImpactReport(entries=tuple(entries), findings=tuple(findings))
