"""Diagnose models (§60-§62, §102-§103).

Every cause is a *candidate* — ranked by evidence tier, never a verdict.
Promotion follows the §102-§103 hierarchy: STATIC possible -> RUNTIME
observed -> DERIVED correlated (runtime + static/config agree).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Evidence, Model, UnknownFact


class CascadeSignal(StrEnum):
    """§60 hop signals along a cascading-failure path."""

    LATENCY = "LATENCY"
    TIMEOUT = "TIMEOUT"
    RETRY = "RETRY"
    LOAD = "LOAD"


class CauseTier(StrEnum):
    """§102-§103 evidence tier — DERIVED correlates planes, never 'confirmed'."""

    DERIVED = "DERIVED"  # RUNTIME + STATIC/CONFIG agree
    RUNTIME = "RUNTIME"  # observed only
    STATIC = "STATIC"  # config/contract evidence only
    UNKNOWN = "UNKNOWN"  # evidence insufficient


@dataclass(frozen=True, kw_only=True)
class CascadeHop(Model):
    """One hop on a §60 cascade path — service + observed signal."""

    service: str
    signal: CascadeSignal
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ObservedSignal(Model):
    """§62 'Observed' line — what runtime evidence actually showed."""

    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CandidateCause(Model):
    """§62/§103 candidate root cause — ranked by tier, always a candidate."""

    subject: str
    kind: str
    tier: CauseTier
    rank: int
    rationale: str
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiIncidentEpisode(Model):
    """§61 episode joining regression + change + graph + SLO + retry topology."""

    symptom: str
    service: str
    operation: str
    path: tuple[CascadeHop, ...] = ()
    changes: tuple[str, ...] = ()  # change-event summaries
    observed: tuple[ObservedSignal, ...] = ()
    candidates: tuple[CandidateCause, ...] = ()
    slo: tuple[str, ...] = ()  # matching objective names
    affected_services: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DiagnosisReport(Model):
    """§165 diagnose output — episodes + finding unknowns."""

    episodes: tuple[ApiIncidentEpisode, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
