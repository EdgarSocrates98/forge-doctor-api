"""§60-62 diagnose engine: cascading-failure episodes + ranked candidates.

Evidence hierarchy (§102-§103): a cause presents as DERIVED-correlated only
when a config/contract change AND a runtime observation agree on the same
hop. STATIC-only stays STATIC-candidate; RUNTIME-only stays RUNTIME-
observed. Worded as candidates, never verdicts.
"""

from __future__ import annotations

from statistics import median

from forge_doctor_api.analyzers.runtime.execution import DownstreamCall, RequestExecution
from forge_doctor_api.change.model import ChangeEvent, ChangeType
from forge_doctor_api.core.models import Finding, UnknownFact
from forge_doctor_api.diagnose.model import (
    ApiIncidentEpisode,
    CandidateCause,
    CascadeHop,
    CascadeSignal,
    CauseTier,
    DiagnosisReport,
    ObservedSignal,
)
from forge_doctor_api.perf.baseline import split_windows
from forge_doctor_api.reliability.model import ApiReliabilityModel

_REGRESSION_IDS = {"APIPERF001", "APIPERF002", "APIPERF003"}
_CHANGE_HINTS = (
    ChangeType.TIMEOUT_CHANGED,
    ChangeType.RETRY_CHANGED,
    ChangeType.DEPENDENCY_CHANGED,
    ChangeType.RATE_LIMIT_CHANGED,
    ChangeType.VERSION_CHANGED,
)
_MIN_SAMPLES = 8


def _median(xs: list[float]) -> float | None:
    return median(xs) if xs else None


def _is_error_status(status: str | None) -> bool | None:
    if status is None:
        return None
    s = status.lower()
    if s == "error":
        return True
    if s.isdigit():
        return int(s) >= 500
    return False


def _service_key(e: RequestExecution) -> tuple[str, str]:
    return (e.service or "(unknown)", e.operation)


def _hop_signals(
    service: str,
    base_exs: list[RequestExecution],
    cur_exs: list[RequestExecution],
    reliability: ApiReliabilityModel | None,
    executions_by_svc: dict[str, list[RequestExecution]],
    base_by_svc: dict[str, list[RequestExecution]],
    seen: set[str],
) -> tuple[list[CascadeHop], list[ObservedSignal], list[UnknownFact]]:
    """Walk downstream calls of `service` in the current window -> §60 hops."""
    hops: list[CascadeHop] = []
    observed: list[ObservedSignal] = []
    unknowns: list[UnknownFact] = []
    if service in seen:
        return hops, observed, unknowns
    seen.add(service)

    cur_calls = [c for e in cur_exs for c in e.downstream_calls]
    base_calls = [c for e in base_exs for c in e.downstream_calls]
    by_callee: dict[str, list[DownstreamCall]] = {}
    for c in cur_calls:
        if c.callee:
            by_callee.setdefault(c.callee, []).append(c)
        else:
            unknowns.append(UnknownFact(
                subject=service,
                missing="downstream callee identity",
                resolution="record span `peer.service`/`server.address` on client spans",
            ))

    retry_scopes = {
        p.scope: p for p in (reliability.retry_policies if reliability else ())
    }
    for callee in sorted(by_callee):
        calls = by_callee[callee]
        # timeout signal
        timed = sum(
            1 for c in calls
            if _is_error_status(c.status.value if hasattr(c.status, "value") else str(c.status))
            or (c.timeout_ms is not None and c.duration_ms is not None
                and c.duration_ms >= c.timeout_ms)
        )
        if timed:
            hops.append(CascadeHop(
                service=callee, signal=CascadeSignal.TIMEOUT,
                detail=f"{service} observed {timed}/{len(calls)} timed-out call(s) to {callee}",
                evidence=tuple(e for c in calls for e in c.evidence)[:4],
            ))
        # retry signal — observed resends or declared amplification
        observed_retries = sum(c.retries or 0 for c in calls)
        base_retries = sum(
            c.retries or 0 for c in base_calls if c.callee == callee
        )
        scope = retry_scopes.get(f"{service}->{callee}") or retry_scopes.get(service)
        if observed_retries > 0:
            factor = (
                f"{observed_retries / max(base_retries, 1):.0f}x"
                if base_retries
                else f"{observed_retries} resends"
            )
            hops.append(CascadeHop(
                service=callee, signal=CascadeSignal.RETRY,
                detail=f"{service} retried calls to {callee} ({factor})",
                evidence=tuple(e for c in calls for e in c.evidence)[:4],
            ))
            observed.append(ObservedSignal(
                detail=f"retry count toward {callee}: {factor} vs baseline",
            ))
        if scope is not None and scope.max_attempts and scope.max_attempts > 1:
            observed.append(ObservedSignal(
                detail=f"declared retry policy at {scope.scope}: "
                f"max_attempts={scope.max_attempts}",
                evidence=scope.evidence,
            ))
        # load signal — call volume up
        if base_calls:
            base_n = sum(1 for c in base_calls if c.callee == callee)
            cur_n = len(calls)
            if cur_n > base_n * 2 and cur_n >= _MIN_SAMPLES:
                hops.append(CascadeHop(
                    service=callee, signal=CascadeSignal.LOAD,
                    detail=f"calls {service}->{callee} up {base_n} -> {cur_n}/window",
                    evidence=tuple(e for c in calls for e in c.evidence)[:4],
                ))
                observed.append(ObservedSignal(
                    detail=f"request volume toward {callee} increased "
                    f"{base_n} -> {cur_n}",
                ))
        # latency — callee's own executions regressed?
        c_base = [e.duration_ms for e in base_by_svc.get(callee, ()) if e.duration_ms]
        c_cur = [
            e.duration_ms
            for e in executions_by_svc.get(callee, ())
            if e.duration_ms
        ]
        if c_base and c_cur and _median(c_cur) and _median(c_base):
            cm, bm = _median(c_cur), _median(c_base)
            if cm is not None and bm is not None:
                if cm > bm * 1.5:
                    hops.append(CascadeHop(
                        service=callee, signal=CascadeSignal.LATENCY,
                        detail=f"{callee} median latency {bm:.0f} -> {cm:.0f} ms",
                        evidence=tuple(
                            ev for e in executions_by_svc.get(callee, ())[:2]
                            for ev in e.evidence
                        )[:4],
                    ))
                else:
                    observed.append(ObservedSignal(
                        detail=f"{callee} latency stable "
                        f"(median {bm:.0f} -> {cm:.0f} ms)",
                    ))
        # recurse one level into the callee's own downstream calls
        sub_hops, sub_obs, sub_unk = _hop_signals(
            callee, base_by_svc.get(callee, []), executions_by_svc.get(callee, []),
            reliability, executions_by_svc, base_by_svc, seen,
        )
        hops.extend(sub_hops)
        observed.extend(sub_obs)
        unknowns.extend(sub_unk)
    return hops, observed, unknowns


def _tier_rank(tier: CauseTier) -> int:
    return {
        CauseTier.DERIVED: 0,
        CauseTier.RUNTIME: 1,
        CauseTier.STATIC: 2,
        CauseTier.UNKNOWN: 3,
    }[tier]


def _candidates(
    hops: list[CascadeHop],
    events: tuple[ChangeEvent, ...],
    service: str,
    operation: str,
) -> tuple[CandidateCause, ...]:
    """§103 promotion: change+runtime agree -> DERIVED; else single-plane."""
    hop_services = {h.service for h in hops}
    causes: list[CandidateCause] = []
    for event in events:
        if event.type not in _CHANGE_HINTS:
            continue
        hit = event.subject in hop_services or event.subject == service
        if not hit and event.subject.split("->")[0] == service:
            hit = True
        if not hit:
            continue
        corroborated = event.subject in hop_services
        tier = CauseTier.DERIVED if corroborated else CauseTier.STATIC
        causes.append(CandidateCause(
            subject=event.subject,
            kind=event.kind,
            tier=tier,
            rank=0,  # filled after sort
            rationale=(
                f"{event.type.value} on {event.subject}"
                + (
                    " — corroborated by observed runtime signal at the same hop"
                    if corroborated
                    else " — config evidence only, no matching runtime signal"
                )
            ),
            evidence=event.evidence,
        ))
    # runtime-only signals with no matching change -> RUNTIME candidates
    changed_subjects = {e.subject for e in events}
    for hop in hops:
        if hop.service in changed_subjects:
            continue
        if hop.signal in (CascadeSignal.TIMEOUT, CascadeSignal.RETRY):
            causes.append(CandidateCause(
                subject=hop.service,
                kind=f"runtime_{hop.signal.value.lower()}",
                tier=CauseTier.RUNTIME,
                rank=0,
                rationale=f"observed {hop.signal.value.lower()} at {hop.service} "
                "with no matching config change in the diff window",
                evidence=hop.evidence,
            ))
    causes.sort(key=lambda c: (_tier_rank(c.tier), c.subject, c.kind))
    return tuple(
        CandidateCause(
            subject=c.subject, kind=c.kind, tier=c.tier, rank=i + 1,
            rationale=c.rationale, evidence=c.evidence,
            unknowns=c.unknowns or (
                ()
                if c.evidence
                else (
                    UnknownFact(
                        subject=c.subject,
                        missing="evidence path for this candidate cause",
                        resolution="record span/config evidence so the "
                        "candidate can be traced to its source",
                    ),
                )
            ),
        )
        for i, c in enumerate(causes)
    )


def diagnose(
    executions: tuple[RequestExecution, ...],
    findings: tuple[Finding, ...],
    events: tuple[ChangeEvent, ...] = (),
    reliability: ApiReliabilityModel | None = None,
) -> DiagnosisReport:
    """§165 cluster regression findings into candidate-cause episodes."""
    windows, by_window = split_windows(executions)
    episodes: list[ApiIncidentEpisode] = []
    unknowns: list[UnknownFact] = []

    cur_exs_all = by_window[windows[-1]] if windows else []
    base_exs_all = [e for w in windows[:-1] for e in by_window[w]]
    cur_by_svc: dict[str, list[RequestExecution]] = {}
    base_by_svc: dict[str, list[RequestExecution]] = {}
    for e in cur_exs_all:
        cur_by_svc.setdefault(e.service or "(unknown)", []).append(e)
    for e in base_exs_all:
        base_by_svc.setdefault(e.service or "(unknown)", []).append(e)

    regression = [f for f in findings if f.id in _REGRESSION_IDS]
    if not regression:
        unknowns.append(UnknownFact(
            subject="runtime",
            missing="no regression findings in the target window",
            resolution="provide runtime artifacts covering at least two windows",
        ))

    for finding in regression:
        subject = finding.entity_ids[0] if finding.entity_ids else ""
        svc, _, op = subject.partition(":")
        # findings use `svc:operation` subjects; prefer entity ids, else split
        svc_key = svc or "(unknown)"
        cur = [e for e in cur_exs_all if e.service == svc and (not op or e.operation == op)]
        if not cur:
            cur = [e for e in cur_by_svc.get(svc_key, ())]
        base = [e for e in base_exs_all if e.service == svc and (not op or e.operation == op)]

        hops, observed, hop_unknowns = _hop_signals(
            svc_key, base, cur, reliability, cur_by_svc, base_by_svc, set(),
        )
        unknowns.extend(hop_unknowns)
        slo = tuple(sorted(
            o.name
            for o in (reliability.objectives if reliability else ())
            if svc_key in o.name or op in o.name
        ))
        affected = sorted({svc_key, *{h.service for h in hops}})
        episodes.append(ApiIncidentEpisode(
            symptom=finding.description,
            service=svc_key,
            operation=op,
            path=tuple(hops),
            changes=tuple(
                e.detail for e in events
                if e.type in _CHANGE_HINTS
                and (e.subject in affected or e.subject.split("->")[0] == svc_key)
            ),
            observed=tuple(observed),
            candidates=_candidates(hops, events, svc_key, op),
            slo=slo,
            affected_services=tuple(affected),
            evidence=finding.evidence,
            unknowns=tuple(finding.unknowns),
        ))

    episodes.sort(key=lambda e: (e.service, e.operation))
    return DiagnosisReport(episodes=tuple(episodes), unknowns=tuple(unknowns))
