"""Experiment engine (§96-97, §168-169) - synthetic scenarios only.

Experiments evaluate a hypothetical change against a baseline's robust
stats under declared `RequestScenario` constraints. The Doctor never
executes live requests; projections are transparent arithmetic over
declared adjustments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Model,
    UnknownFact,
)
from forge_doctor_api.perf.stats import RobustStats


class ExperimentVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONSTRAINT_VIOLATED = "CONSTRAINT_VIOLATED"


_OPS = {"<=": float.__le__, ">=": float.__ge__, "<": float.__lt__,
        ">": float.__gt__, "==": float.__eq__}


@dataclass(frozen=True, kw_only=True)
class Constraint(Model):
    """`metric op value` requirement, e.g. `p95 <= 500`."""

    metric: str
    op: str
    value: float
    source: str = "(scenario)"

    def holds(self, observed: float | None) -> bool | None:
        if observed is None:
            return None
        fn = _OPS.get(self.op)
        return fn(observed, self.value) if fn else None


@dataclass(frozen=True, kw_only=True)
class RequestScenario(Model):
    """§97 synthetic request model."""

    route: str
    request_shape: dict[str, str] = field(default_factory=dict)
    concurrency: int | None = None
    payload_bytes: int | None = None
    downstream_behavior: dict[str, float] = field(default_factory=dict)
    expected_constraints: tuple[Constraint, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Experiment(Model):
    """§96 one hypothetical change evaluated against a baseline.

    `adjustments` maps metric names (`p95`, `error_rate`, `retry_rate`,
    `fanout`, `payload_bytes`) to multipliers - e.g. `{"p95": 0.8}`
    projects a 20% latency improvement from a change. `hypothesis` is
    the claim under test (e.g. `p95 < 500`); when it evaluates False the
    verdict is NOT_SUPPORTED.
    """

    name: str
    scenario: RequestScenario
    adjustments: dict[str, float] = field(default_factory=dict)
    hypothesis: Constraint | None = None
    baseline: RobustStats | None = None
    baseline_rates: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ExperimentReport(Model):
    experiment: str
    verdict: ExperimentVerdict
    projected: dict[str, float]
    violated_constraints: tuple[Constraint, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
    confidence: Confidence = Confidence.LOW
    evidence: tuple[Evidence, ...] = ()


def _projected(experiment: Experiment) -> dict[str, float] | None:
    base = experiment.baseline
    if base is None:
        return None
    out: dict[str, float] = {
        "p50": base.p50,
        "p90": base.p90,
        "p95": base.p95,
        "p99": base.p99,
        **experiment.baseline_rates,
    }
    for metric, factor in experiment.adjustments.items():
        if metric in out:
            out[metric] = out[metric] * factor
    if experiment.scenario.payload_bytes is not None:
        out["payload_bytes"] = float(experiment.scenario.payload_bytes)
    return out


def evaluate_experiment(experiment: Experiment) -> ExperimentReport:
    """§169 verdict engine - deterministic projection + constraints."""
    evidence = (
        Evidence(
            kind=EvidenceKind.DERIVED,
            source="(experiment)",
            summary=f"scenario {experiment.scenario.route} "
            f"adjustments={experiment.adjustments}",
        ),
    )
    projected = _projected(experiment)
    if projected is None:
        return ExperimentReport(
            experiment=experiment.name,
            verdict=ExperimentVerdict.INCONCLUSIVE,
            projected={},
            unknowns=(
                UnknownFact(
                    subject=experiment.name,
                    missing="baseline metrics for the scenario route",
                    resolution="provide a RobustStats baseline",
                ),
            ),
            evidence=evidence,
        )
    violated = tuple(
        c
        for c in experiment.scenario.expected_constraints
        if c.holds(projected.get(c.metric)) is False
    )
    if violated:
        return ExperimentReport(
            experiment=experiment.name,
            verdict=ExperimentVerdict.CONSTRAINT_VIOLATED,
            projected=projected,
            violated_constraints=violated,
            evidence=evidence,
        )
    undecidable = [
        c
        for c in experiment.scenario.expected_constraints
        if c.holds(projected.get(c.metric)) is None
    ]
    hypothesis = experiment.hypothesis
    hyp_result = (
        hypothesis.holds(projected.get(hypothesis.metric))
        if hypothesis is not None
        else None
    )
    if hypothesis is not None and hyp_result is False:
        return ExperimentReport(
            experiment=experiment.name,
            verdict=ExperimentVerdict.NOT_SUPPORTED,
            projected=projected,
            evidence=evidence,
        )
    if undecidable or (hypothesis is not None and hyp_result is None):
        missing = [
            UnknownFact(
                subject=f"constraint {c.metric} {c.op} {c.value}",
                missing=f"projected metric '{c.metric}'",
                resolution="declare the metric in adjustments or "
                "baseline rates",
            )
            for c in undecidable
        ]
        if hypothesis is not None and hyp_result is None:
            missing.append(
                UnknownFact(
                    subject=f"hypothesis {hypothesis.metric}",
                    missing=f"projected metric '{hypothesis.metric}'",
                    resolution="declare the metric in adjustments or "
                    "baseline rates",
                )
            )
        return ExperimentReport(
            experiment=experiment.name,
            verdict=ExperimentVerdict.INCONCLUSIVE,
            projected=projected,
            unknowns=tuple(missing),
            evidence=evidence,
        )
    if not experiment.scenario.expected_constraints and hypothesis is None:
        return ExperimentReport(
            experiment=experiment.name,
            verdict=ExperimentVerdict.INCONCLUSIVE,
            projected=projected,
            unknowns=(
                UnknownFact(
                    subject=experiment.name,
                    missing="expected_constraints or a hypothesis on the "
                    "scenario",
                    resolution="declare constraints so a verdict can "
                    "be supported",
                ),
            ),
            evidence=evidence,
        )
    return ExperimentReport(
        experiment=experiment.name,
        verdict=ExperimentVerdict.SUPPORTED,
        projected=projected,
        evidence=evidence,
    )
