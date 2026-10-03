"""§151-153 declared cache models — evidence-only, never defaults."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    Model,
    Severity,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.security.model import FindingClass


class CacheLayer(StrEnum):
    CLIENT = "client"
    CDN = "cdn"
    GATEWAY = "gateway"
    SERVICE = "service"
    DATABASE = "database"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class CachePolicy(Model):
    """§151 — one declared cache policy.

    Fields are `None` unless the source declared them; `location` names
    the *source file* while `layer` names the §152 cache tier.
    """

    subject: str            # operation or scope this policy covers
    layer: CacheLayer
    ttl: str | None = None
    key: str | None = None
    invalidation: str | None = None
    stale_policy: str | None = None
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class InvalidationRisk(Model):
    """§153 — cached entity that also has mutation evidence."""

    subject: str
    detail: str
    severity: Severity = Severity.MEDIUM
    confidence: Confidence = Confidence.LOW
    finding_class: FindingClass = FindingClass.CANDIDATE
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiCacheModel(Model):
    policies: tuple[CachePolicy, ...] = ()
    risks: tuple[InvalidationRisk, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
