"""FanoutSignal (§59) — handler dependency fan-out, two evidence tiers.

Static candidate: distinct outbound call-site targets in a handler's
source file — emitted only when attribution is unambiguous (a single
handler per file). Runtime confirmed: distinct callees in
`RequestExecution.downstream_calls` for the operation. Runtime evidence
outranks static per §102; nothing is guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.routes.model import RouteModel, RouteScan
from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    Model,
    SourceLocation,
    UnknownFact,
)


class FanoutStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True, kw_only=True)
class FanoutSignal(Model):
    """One operation's dependency fan-out (§59)."""

    subject: str
    static_width: int | None = None
    runtime_width: int | None = None
    status: FanoutStatus
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


def _subject(route: RouteModel) -> str:
    return f"{route.method} {route.path}"


def _static_widths(
    routes: RouteScan, clients: ApiClientModel
) -> tuple[dict[str, tuple[int, SourceLocation]],
           dict[str, list[UnknownFact]]]:
    """subject -> (distinct-target count, location); ambiguous → unknowns."""
    by_file: dict[str, set[str]] = {}
    for site in clients.call_sites:
        target = site.url or site.path
        if target:
            by_file.setdefault(site.location.path, set()).add(target)

    widths: dict[str, tuple[int, SourceLocation]] = {}
    unknowns: dict[str, list[UnknownFact]] = {}
    handlers_by_file: dict[str, list[RouteModel]] = {}
    for r in routes.routes:
        handlers_by_file.setdefault(r.source_location.path, []).append(r)
    for path, rs in handlers_by_file.items():
        targets = by_file.get(path, set())
        if not targets:
            continue
        if len(rs) == 1:
            widths[_subject(rs[0])] = (len(targets), rs[0].source_location)
        else:
            for r in rs:
                unknowns.setdefault(_subject(r), []).append(UnknownFact(
                    subject=_subject(r),
                    missing="per-handler call-site attribution",
                    resolution=(
                        f"{len(rs)} handlers share {path}; "
                        "fan-out cannot be split statically")))
    return widths, unknowns


def _runtime_widths(
    executions: tuple[RequestExecution, ...],
) -> dict[str, tuple[int, tuple[Evidence, ...]]]:
    by_op: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    for e in executions:
        for dc in e.downstream_calls:
            callee = dc.callee or dc.operation
            if callee:
                by_op.setdefault(e.operation, set()).add(callee)
                for ev in dc.evidence:
                    sources.setdefault(e.operation, set()).add(ev.source)
        if e.operation in by_op and not sources.get(e.operation):
            ref = e.trace_id or e.request_id or "runtime"
            sources[e.operation] = {f"trace:{ref}"}
    return {
        op: (
            len(callees),
            tuple(Evidence(
                kind=EvidenceKind.RUNTIME, source=s,
                summary=f"{op} observed calling {len(callees)} callee(s)")
                for s in sorted(sources.get(op, ()))),
        )
        for op, callees in by_op.items()
    }


def fanout_signals(
    routes: RouteScan,
    clients: ApiClientModel,
    executions: tuple[RequestExecution, ...] = (),
    subjects: tuple[str, ...] = (),
) -> tuple[FanoutSignal, ...]:
    """§59 — static candidates + runtime-confirmed fanout, merged.

    A row is emitted for every measured subject, every subject carrying
    an attribution unknown, and every subject in `subjects` — the latter
    as an explicit CANDIDATE with `None` widths (caller asked for it).
    Subjects that were never measured and never asked produce no rows.
    """
    static, unknowns = _static_widths(routes, clients)
    runtime = _runtime_widths(executions)
    signals: list[FanoutSignal] = []
    for subject in sorted({*static, *runtime, *unknowns, *subjects}):
        sw = static.get(subject)
        rw = runtime.get(subject)
        ev: list[Evidence] = []
        if sw is not None:
            width, loc = sw
            ev.append(Evidence(
                kind=EvidenceKind.STATIC, source=loc.path, line=loc.line,
                summary=f"handler calls {width} distinct target(s)"))
        if rw is not None:
            ev.extend(rw[1])
        signals.append(FanoutSignal(
            subject=subject,
            static_width=sw[0] if sw else None,
            runtime_width=rw[0] if rw else None,
            status=(FanoutStatus.CONFIRMED if rw is not None
                    else FanoutStatus.CANDIDATE),
            evidence=tuple(ev),
            unknowns=tuple(unknowns.get(subject, ())),
        ))
    return tuple(signals)
