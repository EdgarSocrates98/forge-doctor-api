"""§104 remediation classification — SAFE / REVIEW_REQUIRED / MANUAL_ONLY.

Classification only: nothing generates or applies fixes here. The table is
deterministic; anything unmapped defaults to MANUAL_ONLY (default-deny).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Evidence, Model, SourceLocation, UnknownFact


class FixClass(StrEnum):
    """§104 three classes — ordering is severity (list order = strictness)."""

    SAFE = "SAFE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MANUAL_ONLY = "MANUAL_ONLY"


class FixType(StrEnum):
    """Fix-type vocabulary keyed in the §104 rule table."""

    # SAFE members (§104)
    METADATA_MISSING = "metadata_missing"          # explicit OpenAPI metadata
    DEPRECATED_CONFIG_RENAME = "deprecated_config_rename"
    DOC_FIELD = "doc_field"
    SPEC_NORMALIZATION = "spec_normalization"
    # REVIEW_REQUIRED members (§104)
    TIMEOUT = "timeout"
    RETRY = "retry"
    CACHE = "cache"
    PAGINATION_DEFAULT = "pagination_default"
    # MANUAL_ONLY members (§104)
    AUTH = "auth"
    AUTHORIZATION = "authorization"
    BREAKING_CONTRACT = "breaking_contract"
    GATEWAY_ROUTING = "gateway_routing"
    TLS = "tls"
    RATE_LIMIT = "rate_limit"
    SCHEMA_REMOVAL = "schema_removal"
    # default-deny
    UNMAPPED = "unmapped"


_CLASS_RANK = {FixClass.SAFE: 0, FixClass.REVIEW_REQUIRED: 1, FixClass.MANUAL_ONLY: 2}


@dataclass(frozen=True, kw_only=True)
class Remediation(Model):
    """§5 Remediation, extended: proposed change + class + justification."""

    proposed_change: str
    target: str
    classification: FixClass
    justification: str
    fix_types: tuple[FixType, ...] = ()
    finding_id: str | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RemediationReport(Model):
    """Classified remediation candidates grouped by class (§104)."""

    candidates: tuple[Remediation, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def by_class(self, cls: FixClass) -> tuple[Remediation, ...]:
        return tuple(c for c in self.candidates if c.classification is cls)
