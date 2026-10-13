"""§77-§83 migration intelligence models.

Analysis only - nothing here generates target contracts or migration code.
Every assessment is a rollup of mandatory dimension results; a "clean"
verdict without full dimension coverage is a bug (spec §79/§81).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Evidence, Model, UnknownFact


class MigrationKind(StrEnum):
    """§77 supported migration analyses."""

    REST_TO_GRPC = "rest-to-grpc"
    REST_TO_GRAPHQL = "rest-to-graphql"
    GATEWAY_TO_GATEWAY = "gateway-to-gateway"
    SYNC_TO_ASYNC = "sync-to-async"
    CONTRACT_VERSION = "contract-version"
    VERSION_UPGRADE = "version-upgrade"  # v1 -> v2 semantic diff


class MigrationClass(StrEnum):
    """§78 migration classifications, worst-first ordering in `RANK`."""

    DIRECT = "DIRECT"
    APPROXIMATE = "APPROXIMATE"
    REDESIGN_REQUIRED = "REDESIGN_REQUIRED"
    NO_EQUIVALENT = "NO_EQUIVALENT"
    UNKNOWN = "UNKNOWN"


# Rollup precedence - worst observed dimension wins. UNKNOWN outranks
# APPROXIMATE because an unassessed dimension must not yield a clean verdict;
# REDESIGN_REQUIRED/NO_EQUIVALENT outrank UNKNOWN because a proven blocker is
# more informative than missing evidence.
_RANK = {
    MigrationClass.DIRECT: 0,
    MigrationClass.APPROXIMATE: 1,
    MigrationClass.UNKNOWN: 2,
    MigrationClass.REDESIGN_REQUIRED: 3,
    MigrationClass.NO_EQUIVALENT: 4,
}


def rollup(classes: list[MigrationClass]) -> MigrationClass:
    if not classes:
        return MigrationClass.UNKNOWN
    return max(classes, key=lambda c: _RANK[c])


@dataclass(frozen=True, kw_only=True)
class DimensionResult(Model):
    """One §79/§81 comparison dimension, evidence-bearing."""

    dimension: str
    classification: MigrationClass
    detail: str
    evidence: tuple[Evidence, ...] = ()
    preserved: tuple[str, ...] = ()
    lost: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class MigrationAssessment(Model):
    """Per-element migration verdict: classification + semantics kept/lost."""

    subject: str
    kind: MigrationKind
    classification: MigrationClass
    dimensions: tuple[DimensionResult, ...]
    preserved: tuple[str, ...] = ()
    lost: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class SdkImpact(Model):
    """§83 one contract change that alters the generated SDK surface."""

    subject: str
    kind: str
    affects_sdk: bool | None  # None = could not determine
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiMigrationIntelligence(Model):
    """§77 analysis result for one migration kind over a project."""

    kind: MigrationKind
    source: str
    target: str
    assessments: tuple[MigrationAssessment, ...] = ()
    sdk_impacts: tuple[SdkImpact, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


class DecisionQuestion(StrEnum):
    """§167 decision-intelligence questions the doctor can brief on."""

    CAN_MOVE_TO_GRPC = "can-move-to-grpc"
    CAN_BECOME_ASYNC = "can-become-async"
    CAN_RETIRE_VERSION = "can-retire-version"
    CAN_ENABLE_RETRY_SAFELY = "can-enable-retry-safely"


@dataclass(frozen=True, kw_only=True)
class DecisionBrief(Model):
    """§167 facts/constraints/capabilities/tradeoffs/unknowns - no verdict."""

    question: str
    subject: str
    facts: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
