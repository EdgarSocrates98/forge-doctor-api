"""Change intelligence models (§65, §67, §68, §179).

`ChangeEvent` is the typed downstream-consumable form of a diff element:
every event traces to exactly one diff element (DERIVED evidence) and is
operation/element-level, never file level.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.checks.compat import ChangeSide, CompatibilityClass, ContractDiff
from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)


class ChangeType(StrEnum):
    """§65 semantic change taxonomy — one type per event."""

    ENDPOINT_ADDED = "ENDPOINT_ADDED"
    ENDPOINT_REMOVED = "ENDPOINT_REMOVED"
    METHOD_CHANGED = "METHOD_CHANGED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    AUTH_CHANGED = "AUTH_CHANGED"
    TIMEOUT_CHANGED = "TIMEOUT_CHANGED"
    RETRY_CHANGED = "RETRY_CHANGED"
    RATE_LIMIT_CHANGED = "RATE_LIMIT_CHANGED"
    DEPENDENCY_CHANGED = "DEPENDENCY_CHANGED"
    VERSION_CHANGED = "VERSION_CHANGED"


@dataclass(frozen=True, kw_only=True)
class ChangeEvent(Model):
    """§65 one typed semantic change derived from a diff element.

    - `type`: §65 taxonomy type.
    - `kind`: the underlying diff kind (e.g. `param_added_required`,
      `timeout_ms_decreased`) — finer than `type` and preserved so
      downstream engines can consume without re-diffing.
    - `subject`: stable semantic identity — operation identity, config
      scope, dependency host, or document subject. Never a file name.
    - `evidence`: DERIVED — cites the diff element this event came from.
    """

    type: ChangeType
    kind: str
    classification: CompatibilityClass
    side: ChangeSide
    subject: str
    detail: str
    before: str | None = None
    after: str | None = None
    path: str | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()
    entity_ids: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ChangeReport(Model):
    """§66 output: typed change events + the raw contract diff."""

    events: tuple[ChangeEvent, ...] = ()
    diff: ContractDiff | None = None
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PrIntelSummary(Model):
    """§67 PR intelligence summary.

    All six counters are always present — `unknowns` is never dropped or
    folded into another counter; an unknown count means the diff could not
    fully classify that many elements.
    """

    breaking_changes: int = 0
    affected_clients: int = 0
    new_public_endpoints: int = 0
    authorization_changes: int = 0
    slo_relevant_dependency_changes: int = 0
    unknowns: int = 0


@dataclass(frozen=True, kw_only=True)
class BaselineEntry(Model):
    """§179 one stored fingerprint anchor."""

    fingerprint: str
    label: str
    recorded_at: str
    subject_count: int = 0


@dataclass(frozen=True, kw_only=True)
class BackwardCompatibilityBaseline(Model):
    """§179 store of contract fingerprints used as diff anchors.

    Ordered deterministically by fingerprint. Entries are compact —
    fingerprint + label + timestamp only; never raw contract payloads.
    """

    entries: tuple[BaselineEntry, ...] = ()

    def latest(self) -> BaselineEntry | None:
        return self.entries[-1] if self.entries else None

    def get(self, fingerprint: str) -> BaselineEntry | None:
        for entry in self.entries:
            if entry.fingerprint == fingerprint:
                return entry
        return None

    def record(self, entry: BaselineEntry) -> BackwardCompatibilityBaseline:
        """Return a new baseline with `entry` stored (replaces same fingerprint)."""
        kept = tuple(e for e in self.entries if e.fingerprint != entry.fingerprint)
        return BackwardCompatibilityBaseline(
            entries=tuple(sorted((*kept, entry), key=lambda e: e.fingerprint))
        )
