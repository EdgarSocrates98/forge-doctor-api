"""§98-§101, §199-§201 Forge Lab models.

A lab scenario is a fixture tree plus machine-readable `expected.yaml`
ground truth. Forbidden expectations bind as strongly as expected ones
(§199); matching is order-insensitive but never content-tolerant.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Model


@dataclass(frozen=True, kw_only=True)
class LabExpectation(Model):
    """§199 ground truth for one scenario.

    `findings`/`forbidden_findings` accept check ids or `PREFIX*` family
    globs (e.g. `OAS*` forbids every OpenAPI check firing).
    """

    findings: tuple[str, ...] = ()
    forbidden_findings: tuple[str, ...] = ()
    description_contains: tuple[str, ...] = ()
    forbidden_description_contains: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    edges: tuple[str, ...] = ()
    forbidden_entities: tuple[str, ...] = ()
    forbidden_edges: tuple[str, ...] = ()
    clients: tuple[str, ...] = ()
    breaking: tuple[str, ...] = ()
    runtime_signals: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class LabScenario(Model):
    """One `labs/<domain>/<name>/` case."""

    domain: str
    name: str
    path: str
    run: tuple[str, ...] = ()  # pipelines: empty -> default static set
    diff_old: str | None = None  # scenario-relative old/new roots for diffs
    diff_new: str | None = None
    hops: tuple[str, ...] = ()  # explicit RELAPI path for the scenario
    today: str | None = None  # deterministic evaluation date for policy
    expected: LabExpectation = LabExpectation()


@dataclass(frozen=True, kw_only=True)
class LabResult(Model):
    """One scenario outcome."""

    domain: str
    name: str
    passed: bool
    missing_findings: tuple[str, ...] = ()
    unexpected_findings: tuple[str, ...] = ()
    forbidden_hits: tuple[str, ...] = ()
    missing_entities: tuple[str, ...] = ()
    missing_edges: tuple[str, ...] = ()
    forbidden_entity_hits: tuple[str, ...] = ()
    forbidden_edge_hits: tuple[str, ...] = ()
    missing_clients: tuple[str, ...] = ()
    missing_breaking: tuple[str, ...] = ()
    missing_runtime_signals: tuple[str, ...] = ()
    missing_issues: tuple[str, ...] = ()
    wording_violations: tuple[str, ...] = ()
    observed_findings: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class FamilyScore(Model):
    """§200 precision/recall per rule family (check-id prefix)."""

    family: str
    expected: int = 0
    hits: int = 0
    misses: int = 0
    false_positives: int = 0

    @property
    def precision(self) -> float | None:
        total = self.hits + self.false_positives
        return self.hits / total if total else None

    @property
    def recall(self) -> float | None:
        total = self.hits + self.misses
        return self.hits / total if total else None


@dataclass(frozen=True, kw_only=True)
class LabReport(Model):
    """§200 full lab pass: per-scenario results + per-family scores."""

    results: tuple[LabResult, ...] = ()
    families: tuple[FamilyScore, ...] = ()

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)
