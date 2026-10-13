"""Policy models (§105-§107, §186-§189).

Policies are declarative data — a YAML policy document names a rule
template, a scope level, and params. Evaluation is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    Severity,
    SourceLocation,
    UnknownFact,
)


class PolicyLevel(StrEnum):
    """§106 inheritance chain — widest to narrowest."""

    ORGANIZATION = "organization"
    DOMAIN = "domain"
    WORKSPACE = "workspace"
    REPO = "repo"


_LEVEL_ORDER = {
    PolicyLevel.ORGANIZATION: 0,
    PolicyLevel.DOMAIN: 1,
    PolicyLevel.WORKSPACE: 2,
    PolicyLevel.REPO: 3,
}


def level_rank(level: PolicyLevel) -> int:
    return _LEVEL_ORDER[level]


@dataclass(frozen=True, kw_only=True)
class ApiPolicy(Model):
    """§105 one declarative policy binding a rule template to params.

    `applies_to`: selector map — `path_prefixes`, `methods`, `tags`.
    `params`: rule-specific (e.g. `min_days` for deprecation).
    """

    id: str
    rule: str
    title: str = ""
    level: PolicyLevel = PolicyLevel.REPO
    severity: Severity | None = None
    enabled: bool = True
    applies_to: tuple[str, ...] = ()  # path prefixes or "*" for all
    params: tuple[tuple[str, str], ...] = ()
    file: str = ""  # provenance — which policy file declared it
    location: SourceLocation | None = None

    def param(self, name: str) -> str | None:
        return dict(self.params).get(name)


@dataclass(frozen=True, kw_only=True)
class PolicyException(Model):
    """§107 exception — all fields mandatory; expired/unapproved is invalid."""

    rule: str
    scope: str          # subject pattern the exception covers ("*" = all)
    owner: str
    justification: str
    created: str
    expires: str
    approval: str
    file: str = ""
    location: SourceLocation | None = None

    def covers(self, subject: str) -> bool:
        if self.scope == "*":
            return True
        if self.scope.endswith("*"):
            return subject.startswith(self.scope[:-1])
        return subject == self.scope


@dataclass(frozen=True, kw_only=True)
class OwnershipSource(Model):
    """§186 one recorded ownership source hit."""

    source: str  # codeowners|openapi_extension|catalog|service_config|platform_contract
    owner: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiOwnership(Model):
    """§186-187 resolved owner + explicit domain tags for a subject."""

    subject: str
    owner: str | None = None
    domain: str | None = None
    tags: tuple[str, ...] = ()
    sources: tuple[OwnershipSource, ...] = ()
    precedence: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PolicySet(Model):
    """Loaded policy documents + exceptions for evaluation."""

    policies: tuple[ApiPolicy, ...] = ()
    exceptions: tuple[PolicyException, ...] = ()
    issues: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
