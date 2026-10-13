"""`ApiVersionModel` + lifecycle model (§18, §19, §7.4, spec 010).

Versions are detected, never inferred from naming: only URI segments
(`/v2/`), header parameters (`api-version`, ...), and media-type versions
(`vnd.x.v2+json`, `version=`) count (§18). Lifecycle comes exclusively from
explicit evidence (`deprecated`, `x-*` lifecycle extensions); an API with no
lifecycle metadata is UNKNOWN — never masqueraded as ACTIVE (§7.4).
`clients_remaining`/`traffic_remaining` require runtime evidence and are
recorded as unknowns here (§19).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)


class VersionMechanism(StrEnum):
    URI = "uri"
    HEADER = "header"
    MEDIA_TYPE = "media_type"


class LifecycleState(StrEnum):
    """§7.4 lifecycle states."""

    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    SUNSET = "SUNSET"
    RETIRED = "RETIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class ApiVersion(Model):
    """One detected version identifier with its detection mechanism."""

    identifier: str
    mechanism: VersionMechanism
    evidence: tuple[Evidence, ...] = ()
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class DeprecationModel(Model):
    """§19 lifecycle fields — populated only from explicit metadata."""

    deprecated: bool = False
    deprecation_date: str | None = None
    sunset_date: str | None = None
    replacement: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiVersionModel(Model):
    """Version + lifecycle view of one parsed contract project."""

    versions: tuple[ApiVersion, ...] = ()
    lifecycle: LifecycleState = LifecycleState.UNKNOWN
    lifecycle_evidence: tuple[Evidence, ...] = ()
    deprecation: DeprecationModel = DeprecationModel()
    unknowns: tuple[UnknownFact, ...] = ()
