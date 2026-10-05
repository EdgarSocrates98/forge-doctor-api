"""§199-§201 lab evaluation: expectations vs observations.

Matching is order-insensitive; content is exact. Expected entries use
exact ids; a trailing `*` makes the entry a family glob (`OAS*`). Every
unexpected finding counts as a false positive for its family (§200).
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from time import perf_counter

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.lab.capabilities import (
    extras_absent,
    extras_present,
    missing_extras,
    scenario_requirements,
)
from forge_doctor_api.lab.loader import discover_scenarios
from forge_doctor_api.lab.model import (
    FamilyScore,
    LabReport,
    LabResult,
    LabScenario,
)
from forge_doctor_api.lab.runner import LabObservations, run_scenario


def _family(check_id: str) -> str:
    return "".join(c for c in check_id if not c.isdigit())


def _matches(entry: str, actual_id: str) -> bool:
    if entry.endswith("*"):
        return actual_id.startswith(entry[:-1])
    return actual_id == entry


def _missing(expected: tuple[str, ...], observed: list[str]) -> tuple[str, ...]:
    return tuple(e for e in expected if not any(e in x for x in observed))


def compare(scenario: LabScenario, obs: LabObservations) -> LabResult:
    """Compare observations to ground truth; both directions are binding."""
    exp = scenario.expected
    actual_ids = sorted({f.id for f in obs.findings})
    descriptions = [f"{f.title} {f.description}" for f in obs.findings]
    corpus = "\n".join(descriptions)

    missing_findings = tuple(
        e for e in exp.findings if not any(_matches(e, a) for a in actual_ids)
    )
    forbidden_hits = tuple(
        a for a in actual_ids
        if any(_matches(e, a) for e in exp.forbidden_findings)
    )
    unexpected = tuple(
        a for a in actual_ids
        if not any(_matches(e, a) for e in exp.findings)
        and not any(_matches(e, a) for e in exp.forbidden_findings)
    )
    wording = tuple(
        e for e in exp.description_contains
        if not any(e in d for d in descriptions)
    ) + tuple(
        f"forbidden wording {w!r} present"
        for w in exp.forbidden_description_contains
        if w in corpus
    )
    issues_text = "\n".join(obs.issues)
    missing_entities = _missing(exp.entities, obs.entities)
    missing_edges = _missing(exp.edges, obs.edges)
    forbidden_entity_hits = tuple(
        e for e in exp.forbidden_entities if any(e in x for x in obs.entities)
    )
    forbidden_edge_hits = tuple(
        e for e in exp.forbidden_edges if any(e in x for x in obs.edges)
    )
    missing_clients = _missing(exp.clients, obs.clients)
    missing_breaking = tuple(
        b for b in exp.breaking if not any(b in s for s in obs.breaking)
    )
    missing_runtime_signals = tuple(
        s for s in exp.runtime_signals
        if s not in obs.runtime_signals
        and not any(_matches(s, a) for a in actual_ids)
    )
    missing_issues = tuple(i for i in exp.issues if i not in issues_text)
    passed = not any((
        missing_findings, unexpected, forbidden_hits,
        missing_entities, missing_edges,
        forbidden_entity_hits, forbidden_edge_hits,
        missing_clients, missing_breaking,
        missing_runtime_signals, missing_issues, wording,
        scenario.problems,
    ))
    return LabResult(
        domain=scenario.domain,
        name=scenario.name,
        passed=passed,
        problems=scenario.problems,
        sample_size=obs.sample_size,
        elapsed_ms=obs.elapsed_ms,
        peak_bytes=obs.peak_bytes,
        unknowns=obs.unknowns,
        parse_failures=obs.parse_failures,
        unsupported=obs.unsupported,
        missing_findings=missing_findings,
        unexpected_findings=unexpected,
        forbidden_hits=forbidden_hits,
        missing_entities=missing_entities,
        missing_edges=missing_edges,
        forbidden_entity_hits=forbidden_entity_hits,
        forbidden_edge_hits=forbidden_edge_hits,
        missing_clients=missing_clients,
        missing_breaking=missing_breaking,
        missing_runtime_signals=missing_runtime_signals,
        missing_issues=missing_issues,
        wording_violations=wording,
        observed_findings=tuple(actual_ids),
    )


def run_labs(context: ProjectContext) -> LabReport:
    """Discover + run every scenario under `context`, then score it.

    A scenario whose declared capability requirements (`requires_extras`,
    domain/pipeline-implied extras) are absent from this install profile
    is `skipped` — recorded with its reason, counted separately, never a
    failure and never a silent pass.

    Per-scenario timing/memory are *measurements* of the harness run,
    recorded on the result — never inputs to matching.
    """
    scenarios = discover_scenarios(context)
    pairs: list[tuple[LabScenario, LabResult]] = []
    for scenario in scenarios:
        missing = missing_extras(scenario_requirements(scenario))
        if missing:
            pairs.append((scenario, LabResult(
                domain=scenario.domain,
                name=scenario.name,
                passed=False,
                skipped=True,
                skip_reason="missing extras: " + ", ".join(missing),
                problems=scenario.problems,
            )))
            continue
        tracemalloc.start()
        t0 = perf_counter()
        obs = run_scenario(context, scenario)
        obs.elapsed_ms = int((perf_counter() - t0) * 1000)
        _, obs.peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        pairs.append((scenario, compare(scenario, obs)))
    return LabReport(
        results=tuple(r for _, r in pairs),
        families=aggregate_scores(pairs),
        extras_present=extras_present(),
        extras_absent=extras_absent(),
    )


def aggregate_scores(
    pairs: list[tuple[LabScenario, LabResult]],
) -> tuple[FamilyScore, ...]:
    """§200 per-family precision over expectations + observations."""
    stats: dict[str, dict[str, int]] = {}

    def stat(family: str) -> dict[str, int]:
        return stats.setdefault(
            family, {"expected": 0, "hits": 0, "misses": 0,
                     "false_positives": 0, "sample_size": 0,
                     "unknowns": 0, "unsupported": 0,
                     "parse_failures": 0, "elapsed_ms": 0,
                     "peak_bytes": 0}
        )

    for scenario, result in pairs:
        if result.skipped:
            continue  # unrun scenarios contribute no evidence either way
        for entry in scenario.expected.findings:
            fam = _family(entry.rstrip("*"))
            stat(fam)["expected"] += 1
            hit = any(_matches(entry, a) for a in result.observed_findings)
            stat(fam)["hits" if hit else "misses"] += 1
        for a in (*result.unexpected_findings, *result.forbidden_hits):
            stat(_family(a))["false_positives"] += 1
        for entry in scenario.expected.findings:
            fam = _family(entry.rstrip("*"))
            s = stat(fam)
            s["sample_size"] += result.sample_size
            s["unknowns"] += result.unknowns
            s["unsupported"] += result.unsupported
            s["parse_failures"] += result.parse_failures
            s["elapsed_ms"] += result.elapsed_ms
            s["peak_bytes"] = max(s["peak_bytes"], result.peak_bytes)
    return tuple(
        FamilyScore(
            family=fam,
            expected=s["expected"],
            hits=s["hits"],
            misses=s["misses"],
            false_positives=s["false_positives"],
            sample_size=s["sample_size"],
            unknowns=s["unknowns"],
            unsupported=s["unsupported"],
            parse_failures=s["parse_failures"],
            elapsed_ms=s["elapsed_ms"],
            peak_bytes=s["peak_bytes"],
        )
        for fam, s in sorted(stats.items())
    )


def write_run_record(report: LabReport, runs_dir: Path, timestamp: str) -> Path:
    """Persist a lab pass under `factory/runs/` as evidence."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{timestamp}.lab.json"
    path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
