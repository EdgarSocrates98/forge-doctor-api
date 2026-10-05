"""§98-§101, §199-§201 Forge Lab models.

A lab scenario is a fixture tree plus machine-readable `expected.yaml`
ground truth. Forbidden expectations bind as strongly as expected ones
(§199); matching is order-insensitive but never content-tolerant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    requires_extras: tuple[str, ...] = ()  # optional extras needed to run
    requires_domains: tuple[str, ...] = ()  # domains whose extras are needed
    expected: LabExpectation = LabExpectation()
    provenance: tuple[tuple[str, str], ...] = ()  # realworld provenance block
    problems: tuple[str, ...] = ()  # structural validation errors


@dataclass(frozen=True, kw_only=True)
class LabResult(Model):
    """One scenario outcome.

    `skipped` means the scenario declared capabilities absent from this
    install profile — it is neither a pass nor a fail, and `skip_reason`
    says exactly what is missing.
    """

    domain: str
    name: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
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
    problems: tuple[str, ...] = ()
    observed_findings: tuple[str, ...] = ()
    # spec-058 measurement fields (harness metrics, never compared)
    sample_size: int = 0         # fixture files scanned
    elapsed_ms: int = 0
    peak_bytes: int = 0
    unknowns: int = 0
    parse_failures: int = 0
    unsupported: int = 0


@dataclass(frozen=True, kw_only=True)
class FamilyScore(Model):
    """§200 precision/recall per rule family (check-id prefix)."""

    family: str
    expected: int = 0
    hits: int = 0
    misses: int = 0
    false_positives: int = 0
    # spec-058 aggregates over the scenarios exercising this family
    sample_size: int = 0
    unknowns: int = 0
    unsupported: int = 0
    parse_failures: int = 0
    elapsed_ms: int = 0
    peak_bytes: int = 0

    @property
    def tp(self) -> int:
        return self.hits

    @property
    def fp(self) -> int:
        return self.false_positives

    @property
    def fn(self) -> int:
        return self.misses

    @property
    def precision(self) -> float | None:
        total = self.hits + self.false_positives
        return self.hits / total if total else None

    @property
    def recall(self) -> float | None:
        total = self.hits + self.misses
        return self.hits / total if total else None

    @property
    def unknown_rate(self) -> float | None:
        return (self.unknowns / self.sample_size
                if self.sample_size else None)

    @property
    def unsupported_rate(self) -> float | None:
        return (self.unsupported / self.sample_size
                if self.sample_size else None)

    @property
    def coverage_confidence(self) -> str:
        """Documented heuristic — a band, never a claim.

        <10 expected+observed items -> "low"; >=10 -> "medium".
        There is no "high": lab coverage is always partial evidence.
        """
        return "medium" if self.expected + self.sample_size >= 10 else "low"

    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.update({
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": self.precision, "recall": self.recall,
            "unknown_rate": self.unknown_rate,
            "unsupported_rate": self.unsupported_rate,
            "coverage_confidence": self.coverage_confidence,
        })
        return out


@dataclass(frozen=True, kw_only=True)
class LabReport(Model):
    """§200 full lab pass: per-scenario results + per-family scores.

    `extras_present`/`extras_absent` record the install profile the run
    executed under — run records prove which optional capabilities were
    exercised rather than assumed.
    """

    results: tuple[LabResult, ...] = ()
    families: tuple[FamilyScore, ...] = ()
    extras_present: tuple[str, ...] = ()
    extras_absent: tuple[str, ...] = ()

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)

    @property
    def skipped_results(self) -> tuple[LabResult, ...]:
        return tuple(r for r in self.results if r.skipped)
