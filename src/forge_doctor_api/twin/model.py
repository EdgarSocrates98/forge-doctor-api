"""API Digital Twin model (§63, §64, §113).

The twin is a *view* over existing models, never a second storage
layer: each state records compact summaries (counts + fingerprints +
key identifiers) plus evidence references back to its sources.
HYPOTHETICAL is strictly isolated - it can never contaminate OBSERVED
queries (states never borrow each other's confidence, §63).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    UnknownFact,
)

TWIN_MODEL_SCHEMA_VERSION = "twin-model/1"


class TwinState(StrEnum):
    """§63 the five twin states."""

    DESIRED = "DESIRED"
    DECLARED = "DECLARED"
    IMPLEMENTED = "IMPLEMENTED"
    OBSERVED = "OBSERVED"
    HYPOTHETICAL = "HYPOTHETICAL"


@dataclass(frozen=True, kw_only=True)
class TwinStateView(Model):
    """Compact normalized projection of one state's evidence."""

    state: TwinState
    present: bool
    record_count: int = 0
    fingerprint: str | None = None
    identifiers: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


class TwinDriftKind(StrEnum):
    """§64 twin drift types."""

    CONTRACT_DRIFT = "CONTRACT_DRIFT"
    AUTH_DRIFT = "AUTH_DRIFT"
    ROUTING_DRIFT = "ROUTING_DRIFT"
    VERSION_DRIFT = "VERSION_DRIFT"
    RUNTIME_DRIFT = "RUNTIME_DRIFT"
    SLO_DRIFT = "SLO_DRIFT"
    DEPENDENCY_DRIFT = "DEPENDENCY_DRIFT"


@dataclass(frozen=True, kw_only=True)
class TwinDrift(Model):
    """§64 a divergence between two named states, cited on both sides."""

    kind: TwinDriftKind
    state_a: TwinState
    state_b: TwinState
    subject: str
    detail: str
    evidence_a: tuple[Evidence, ...] = ()
    evidence_b: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiDigitalTwin(Model):
    """§63 five-state projection over existing models."""

    states: tuple[TwinStateView, ...]
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def view(self, state: TwinState) -> TwinStateView | None:
        for v in self.states:
            if v.state is state:
                return v
        return None


@dataclass(frozen=True, kw_only=True)
class TwinSnapshot(Model):
    """§113 one compact history snapshot - counts + fingerprints only."""

    label: str
    recorded_at: str | None = None
    states: tuple[TwinStateView, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiTwinHistory(Model):
    """§113 versioned snapshots of contract/impl/runtime/client state.

    Compact normalized storage (§172): snapshots keep counts and
    fingerprints, never raw payloads.
    """

    snapshots: tuple[TwinSnapshot, ...] = ()

    def record(self, snapshot: TwinSnapshot) -> ApiTwinHistory:
        return ApiTwinHistory(snapshots=(*self.snapshots, snapshot))

    def ordered(self) -> tuple[TwinSnapshot, ...]:
        return tuple(
            sorted(
                self.snapshots,
                key=lambda s: (s.recorded_at or "", s.label),
            )
        )
