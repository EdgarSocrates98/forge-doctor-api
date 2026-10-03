"""APIPERF001-008 regression engine (§37, §89).

Compares the latest populated window against all earlier windows per
(service, operation) key. Every rule is transparent: the threshold is
stated in the finding, thin samples (< MIN_SAMPLES) never fire, and a
single-window dataset produces no regressions rather than guessing a
baseline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.history import window_key
from forge_doctor_api.checks.perf.catalog import BY_ID, PerfCheckSpec
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.perf.stats import MIN_SAMPLES, robust_stats

# Declared regression thresholds - stated in every finding they produce.
LATENCY_FACTOR = 1.5
LATENCY_MAD_K = 3.0
ERROR_RATE_DELTA = 0.05
RETRY_RATE_DELTA = 0.10
TIMEOUT_RATE_DELTA = 0.05
PAYLOAD_FACTOR = 1.5
FANOUT_DELTA = 1.0
CACHE_HIT_DROP = 0.10


@dataclass(frozen=True)
class _Windows:
    baseline: list[RequestExecution]
    current: list[RequestExecution]
    current_window: str


def _finding(
    spec: PerfCheckSpec,
    description: str,
    subject: str,
    unknowns: tuple[UnknownFact, ...] = (),
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=spec.evidence_kind,
                source="(runtime)",
                summary=description,
            ),
        ),
        source_location=SourceLocation(path="(runtime)"),
        entity_ids=(subject,),
        unknowns=unknowns,
    )


def _split(
    executions: tuple[RequestExecution, ...],
) -> dict[tuple[str | None, str], _Windows]:
    """Latest populated window vs all earlier windows, per op key."""
    by_key: dict[tuple[str | None, str], dict[str, list[RequestExecution]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for e in executions:
        by_key[(e.service, e.operation)][window_key(e.start_unix_nano)].append(e)
    out: dict[tuple[str | None, str], _Windows] = {}
    for key, wins in by_key.items():
        ordered = sorted(wins)
        if len(ordered) < 2:
            continue
        cur_win = ordered[-1]
        base = [e for w in ordered[:-1] for e in wins[w]]
        out[key] = _Windows(base, wins[cur_win], cur_win)
    return out


def _regressed(base: list[float], cur: list[float]) -> tuple[bool, str]:
    """p95 regression: cur.p95 past the declared bound AND p50 shifted.

    The median guard keeps a single-spike window from firing (a lone
    outlier moves p95 through interpolation but never moves p50).
    """
    b, c = robust_stats(base), robust_stats(cur)
    if b is None or c is None:
        return False, ""
    if b.count < MIN_SAMPLES or c.count < MIN_SAMPLES:
        return False, ""
    limit = max(b.p95 * LATENCY_FACTOR, b.p95 + LATENCY_MAD_K * b.mad)
    median_shift = max(b.mad, b.p50 * 0.10)
    if c.p95 > limit and c.p50 > b.p50 + median_shift:
        return True, (
            f"p95 {c.p95:.0f}ms > baseline {b.p95:.0f}ms "
            f"(threshold: max(1.5x, +3*MAD) -> {limit:.0f}ms; "
            f"p50 {c.p50:.0f} > {b.p50:.0f})"
        )
    return False, ""


def _rates(
    exs: list[RequestExecution],
    pick: Callable[[RequestExecution], bool | None],
) -> tuple[int, int]:
    """(hits, total) over executions where `pick` returns a truthy flag."""
    total = 0
    hits = 0
    for e in exs:
        v = pick(e)
        if v is None:
            continue
        total += 1
        if v:
            hits += 1
    return hits, total


def run_perf_checks(
    executions: tuple[RequestExecution, ...],
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    windows = _split(executions)

    for (service, operation), w in sorted(
        windows.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
    ):
        subj = f"{service or '(unknown)'}:{operation}"
        base, cur = w.baseline, w.current

        ok, detail = _regressed(
            [e.duration_ms for e in base if e.duration_ms is not None],
            [e.duration_ms for e in cur if e.duration_ms is not None],
        )
        if ok:
            findings.append(
                _finding(BY_ID["APIPERF001"], f"{subj}: {detail} "
                         f"(window {w.current_window})", subj)
            )

        # APIPERF002 - error rate regression
        b_err = [e for e in base if e.status is not None]
        c_err = [e for e in cur if e.status is not None]

        def _is_err(e: RequestExecution) -> bool | None:
            s = e.status
            if s is None:
                return None
            return s == "error" or (s.isdigit() and int(s) >= 500)

        bh, bt = _rates(b_err, _is_err)
        ch, ct = _rates(c_err, _is_err)
        if bt >= MIN_SAMPLES and ct >= MIN_SAMPLES:
            br, cr = bh / bt, ch / ct
            if cr - br > ERROR_RATE_DELTA:
                findings.append(
                    _finding(
                        BY_ID["APIPERF002"],
                        f"{subj}: error rate {cr:.0%} vs baseline {br:.0%} "
                        f"(threshold +{ERROR_RATE_DELTA:.0%}, "
                        f"window {w.current_window})",
                        subj,
                    )
                )

        # APIPERF003 - downstream regression per callee
        base_calls: dict[str, list[float]] = defaultdict(list)
        cur_calls: dict[str, list[float]] = defaultdict(list)
        for e in base:
            for c in e.downstream_calls:
                if c.callee and c.duration_ms is not None:
                    base_calls[c.callee].append(c.duration_ms)
        for e in cur:
            for c in e.downstream_calls:
                if c.callee and c.duration_ms is not None:
                    cur_calls[c.callee].append(c.duration_ms)
        for callee in sorted(cur_calls):
            ok, detail = _regressed(
                base_calls.get(callee, []), cur_calls[callee]
            )
            if ok:
                findings.append(
                    _finding(
                        BY_ID["APIPERF003"],
                        f"{subj} -> {callee}: downstream {detail} "
                        f"(window {w.current_window})",
                        subj,
                    )
                )

        # APIPERF004 - retry amplification
        bh, bt = _rates(
            base, lambda e: (e.retries or 0) > 0 if e.retries is not None else None
        )
        ch, ct = _rates(
            cur, lambda e: (e.retries or 0) > 0 if e.retries is not None else None
        )
        if bt >= MIN_SAMPLES and ct >= MIN_SAMPLES:
            br, cr = bh / bt, ch / ct
            if cr - br > RETRY_RATE_DELTA:
                findings.append(
                    _finding(
                        BY_ID["APIPERF004"],
                        f"{subj}: observed retry rate {cr:.0%} vs baseline "
                        f"{br:.0%} (threshold +{RETRY_RATE_DELTA:.0%})",
                        subj,
                        unknowns=(
                            UnknownFact(
                                subject=subj,
                                missing="configured retry policies",
                                resolution="observed retries only; join "
                                "reliability config to explain cause",
                            ),
                        ),
                    )
                )

        # APIPERF005 - timeout increase
        bh, bt = _rates(base, lambda e: e.timed_out)
        ch, ct = _rates(cur, lambda e: e.timed_out)
        if bt >= MIN_SAMPLES and ct >= MIN_SAMPLES:
            br, cr = bh / bt, ch / ct
            if cr - br > TIMEOUT_RATE_DELTA:
                findings.append(
                    _finding(
                        BY_ID["APIPERF005"],
                        f"{subj}: timeout rate {cr:.0%} vs baseline "
                        f"{br:.0%} (threshold +{TIMEOUT_RATE_DELTA:.0%})",
                        subj,
                    )
                )

        # APIPERF006 - payload growth
        ok, detail = _regressed(
            [float(e.response_bytes) for e in base
             if e.response_bytes is not None],
            [float(e.response_bytes) for e in cur
             if e.response_bytes is not None],
        )
        if ok:
            findings.append(
                _finding(
                    BY_ID["APIPERF006"],
                    f"{subj}: payload {detail} "
                    f"(window {w.current_window})",
                    subj,
                )
            )

        # APIPERF007 - fan-out increase
        bf = [float(len(e.downstream_calls)) for e in base]
        cf = [float(len(e.downstream_calls)) for e in cur]
        if len(bf) >= MIN_SAMPLES and len(cf) >= MIN_SAMPLES:
            bm = sum(bf) / len(bf)
            cm = sum(cf) / len(cf)
            if cm - bm > FANOUT_DELTA:
                findings.append(
                    _finding(
                        BY_ID["APIPERF007"],
                        f"{subj}: mean fan-out {cm:.1f} vs baseline "
                        f"{bm:.1f} (threshold +{FANOUT_DELTA:.0f})",
                        subj,
                    )
                )

        # APIPERF008 - cache effectiveness regression
        def _hit(e: RequestExecution) -> bool | None:
            cs = e.cache_status
            if cs is None:
                return None
            return "hit" in cs.lower()

        bh, bt = _rates(base, _hit)
        ch, ct = _rates(cur, _hit)
        if bt >= MIN_SAMPLES and ct >= MIN_SAMPLES:
            br, cr = bh / bt, ch / ct
            if br - cr > CACHE_HIT_DROP:
                findings.append(
                    _finding(
                        BY_ID["APIPERF008"],
                        f"{subj}: cache hit rate {cr:.0%} vs baseline "
                        f"{br:.0%} (threshold -{CACHE_HIT_DROP:.0%})",
                        subj,
                    )
                )

    findings.sort(key=lambda f: (f.id, f.entity_ids, f.description))
    return tuple(findings)
