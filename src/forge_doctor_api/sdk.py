"""§23/§210 public SDK — the stable `Doctor` facade.

Everything behind this facade is deterministic + offline: same input,
same `clock`, same bytes out. Internal modules may move; the exports
listed in `forge_doctor_api.__all__` are the public contract.

Errors surface as typed `DoctorError` subclasses — never bare
tracebacks on user input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.discovery import ArtifactInventory, discover
from forge_doctor_api.core.models import Finding, UnknownFact
from forge_doctor_api.handoff.bundle import assemble_bundle
from forge_doctor_api.handoff.context import context_slice
from forge_doctor_api.handoff.model import ApiHandoffBundle
from forge_doctor_api.knowledge.capability import DetectedCapability
from forge_doctor_api.report import DoctorReport

SDK_VERSION = "0.1.0"


class DoctorError(Exception):
    """Base class for all SDK-facing errors."""


class ProjectUnreadableError(DoctorError):
    """Root path missing, not a directory, or unreadable."""


class FindingNotFoundError(DoctorError):
    """`explain` target not present in the report."""


@dataclass(frozen=True, kw_only=True)
class Explanation:
    """`Doctor.explain` result — finding + evidence + rationale."""

    finding: Finding
    evidence: tuple[str, ...]
    why: str
    unknowns: tuple[UnknownFact, ...]


class Doctor:
    """Deterministic facade over the unified pipeline.

    Holds a `ProjectContext` + optional injected clock; each method is
    a thin, honest projection over `scan_project` — nothing extra is
    computed, nothing is hidden.
    """

    def __init__(
        self,
        context: ProjectContext,
        *,
        clock: date | None = None,
        profile: str | None = None,
    ) -> None:
        self._ctx = context
        self._clock = clock
        self._profile = profile
        self._report: DoctorReport | None = None
        self._inventory: ArtifactInventory | None = None

    @classmethod
    def from_path(
        cls,
        root: str | Path,
        *,
        clock: date | None = None,
        profile: str | None = None,
    ) -> Doctor:
        """Build a Doctor rooted at `root` (typed errors on bad input)."""
        path = Path(root)
        if not path.exists():
            raise ProjectUnreadableError(f"no such path: {root}")
        if not path.is_dir():
            raise ProjectUnreadableError(f"not a directory: {root}")
        try:
            ctx = ProjectContext.from_root(path)
        except Exception as exc:
            raise ProjectUnreadableError(
                f"cannot open project at {root}: {exc}") from exc
        return cls(ctx, clock=clock, profile=profile)

    # -- core ---------------------------------------------------------------

    def scan(self, before: Doctor | Path | None = None) -> DoctorReport:
        """Unified deterministic report; `before` enables the diff."""
        before_ctx = self._before_ctx(before)
        report = self._run(before_ctx)
        if before is None:
            self._report = report
        return report

    def diff(self, before: Doctor | Path) -> DoctorReport:
        """Scan with contract diff against `before`."""
        return self.scan(before)

    def explain(self, finding_id: str) -> Explanation:
        """Finding + evidence + why it fired (typed error when absent)."""
        report = self._cached()
        for f in report.findings:
            if f.id == finding_id or (f.entity_ids and (
                finding_id in f.entity_ids
            )):
                return Explanation(
                    finding=f,
                    evidence=tuple(e.summary for e in f.evidence),
                    why=f"{f.id}: {f.title} — {f.description}",
                    unknowns=f.unknowns,
                )
        raise FindingNotFoundError(
            f"no finding {finding_id!r} in this report")

    # -- projections ----------------------------------------------------------

    def graph(self) -> Any:
        """Graph DomainSummary (None without graph evidence)."""
        return self._cached().graph

    def handoff(self) -> ApiHandoffBundle:
        """Compact V2 handoff bundle over the current report."""
        report = self._cached()
        return assemble_bundle(
            service=report.project,
            findings=report.findings,
            unknowns=report.unknowns,
            handoff_version=2,
            report=report,
        )

    def inventory(self) -> ArtifactInventory:
        """The scan's artifact inventory (recomputed deterministically)."""
        if self._inventory is None:
            self._inventory = discover(self._ctx)
        return self._inventory

    def capabilities(self) -> tuple[DetectedCapability, ...]:
        return self._cached().capabilities

    def slice(self, ref: str) -> Any:
        """doctor:// context slice over the current report."""
        return context_slice(self._cached(), ref)

    # -- internals -------------------------------------------------------------

    def _run(self, before_ctx: ProjectContext | None) -> DoctorReport:
        from forge_doctor_api.scan import scan_project

        return scan_project(
            self._ctx, before=before_ctx, today=self._clock)

    def _cached(self) -> DoctorReport:
        if self._report is None:
            self._report = self._run(None)
        return self._report

    def _before_ctx(
        self, before: Doctor | Path | None
    ) -> ProjectContext | None:
        if before is None:
            return None
        if isinstance(before, Doctor):
            return before._ctx
        path = Path(before)
        if not path.is_dir():
            raise ProjectUnreadableError(f"no such path: {before}")
        return ProjectContext.from_root(path)
