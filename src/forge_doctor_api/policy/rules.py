"""§105/§188 rule templates — deterministic predicates over loaded models.

Each rule returns `PolicyViolation`s for matching subjects. Selectors
(`applies_to` path prefixes) narrow which operations a policy inspects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from forge_doctor_api.analyzers.openapi import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.model import OpenApiOperation, OperationSource
from forge_doctor_api.analyzers.version import ApiVersionModel
from forge_doctor_api.core.models import Evidence, Severity, SourceLocation
from forge_doctor_api.policy.model import ApiOwnership, ApiPolicy
from forge_doctor_api.reliability.model import ApiReliabilityModel
from forge_doctor_api.security.model import ApiSecurityModel


@dataclass(frozen=True, kw_only=True)
class PolicyViolation:
    subject: str
    detail: str
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RuleContext:
    """Everything a policy predicate may read — pre-loaded models."""

    openapi: OpenApiProjectModel | None = None
    security: ApiSecurityModel | None = None
    reliability: ApiReliabilityModel | None = None
    version: ApiVersionModel | None = None
    ownership: tuple[ApiOwnership, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RuleSpec:
    """Built-in rule template: id prefix + metadata + predicate."""

    rule: str
    check_id: str
    title: str
    default_severity: Severity
    predicate: Callable[[RuleContext, ApiPolicy], tuple[PolicyViolation, ...]]


def _selected(policy: ApiPolicy, op: OpenApiOperation) -> bool:
    prefixes = policy.applies_to or ("*",)
    if "*" in prefixes:
        return True
    return any(op.path.startswith(p.rstrip("*")) for p in prefixes)


def _ops(ctx: RuleContext) -> tuple[OpenApiOperation, ...]:
    if ctx.openapi is None:
        return ()
    return tuple(o for o in ctx.openapi.operations if o.source is OperationSource.PATH)


def _require_auth(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    out = []
    for op in _ops(ctx):
        if not _selected(policy, op) or op.has_security:
            continue
        out.append(PolicyViolation(
            subject=op.identity,
            detail=f"{op.method} {op.path} has no security requirement",
            location=op.location,
        ))
    return tuple(out)


def _require_operation_id(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    out = []
    for op in _ops(ctx):
        if not _selected(policy, op) or op.operation_id:
            continue
        out.append(PolicyViolation(
            subject=op.identity,
            detail=f"{op.method} {op.path} has no operationId",
            location=op.location,
        ))
    return tuple(out)


def _require_owner(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    out = []
    for own in ctx.ownership:
        if own.owner is None:
            out.append(PolicyViolation(
                subject=own.subject,
                detail=f"{own.subject} has no resolved owner (§186 sources exhausted)",
            ))
    return tuple(out)


def _require_slo(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    if ctx.reliability is None:
        return ()
    named = {o.name for o in ctx.reliability.objectives}
    # objectives are named; a policy may scope which services must have one
    critical_tags = {p for p in policy.applies_to if p != "*"}
    if not named and "*" in (policy.applies_to or ("*",)):
        return (PolicyViolation(
            subject="(project)",
            detail="no service objectives (SLOs) declared anywhere in config",
        ),)
    out = []
    for own in ctx.ownership:
        if own.owner and not any(own.owner in n or own.subject in n for n in named):
            match = not critical_tags or own.subject in critical_tags or own.domain in critical_tags
            if match:
                out.append(PolicyViolation(
                    subject=own.subject,
                    detail=f"{own.subject} has no matching SLO objective name",
                ))
    return tuple(out)


def _no_wildcard_cors(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    if ctx.security is None:
        return ()
    return tuple(
        PolicyViolation(
            subject=c.scope,
            detail=f"CORS wildcard origin allowed at `{c.scope}`",
            location=c.location,
            evidence=c.evidence,
        )
        for c in ctx.security.cors
        if "*" in c.allowed_origins
    )


def _min_deprecation_days(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    if ctx.version is None or ctx.version.deprecation is None:
        return ()
    dep = ctx.version.deprecation
    if not dep.deprecated:
        return ()
    try:
        min_days = int(policy.param("min_days") or "180")
    except ValueError:
        min_days = 180
    if dep.sunset_date is None:
        return (PolicyViolation(
            subject="(api)",
            detail="deprecated API has no sunset date",
            evidence=dep.evidence,
        ),)
    from datetime import date
    try:
        sunset = date.fromisoformat(dep.sunset_date[:10])
        created = date.fromisoformat((dep.deprecation_date or "")[:10])
    except ValueError:
        return (PolicyViolation(
            subject="(api)",
            detail=f"sunset date {dep.sunset_date!r} not ISO-parseable",
            evidence=dep.evidence,
        ),)
    if dep.deprecation_date and (sunset - created).days < min_days:
        return (PolicyViolation(
            subject="(api)",
            detail=(
                f"sunset {dep.sunset_date} is {(sunset - created).days} days "
                f"after deprecation {dep.deprecation_date} (< {min_days})"
            ),
            evidence=dep.evidence,
        ),)
    return ()


def _doc_coverage(ctx: RuleContext, policy: ApiPolicy) -> tuple[PolicyViolation, ...]:
    """§189 opportunity-level: op/schema/error/deprecation docs."""
    out = []
    resp_by_pointer = (
        {r.pointer: r for r in ctx.openapi.responses} if ctx.openapi is not None else {}
    )
    for op in _ops(ctx):
        if not _selected(policy, op):
            continue
        if not op.description and not op.summary:
            out.append(PolicyViolation(
                subject=op.identity,
                detail=f"{op.method} {op.path} has no description/summary",
                location=op.location,
            ))
        if op.deprecated and not op.description:
            out.append(PolicyViolation(
                subject=op.identity,
                detail=f"{op.method} {op.path} is deprecated without deprecation notes",
                location=op.location,
            ))
        for ptr in op.response_pointers:
            resp = resp_by_pointer.get(ptr)
            if (
                resp is not None
                and resp.status is not None
                and resp.status.startswith(("4", "5"))
                and not resp.description
            ):
                out.append(PolicyViolation(
                    subject=ptr,
                    detail=(
                        f"error response {resp.status} of {op.method} {op.path} "
                        "has no description"
                    ),
                    location=resp.location,
                ))
    if ctx.openapi is not None:
        for schema in ctx.openapi.schemas:
            desc = (
                schema.content.get("description")
                if isinstance(schema.content, dict)
                else None
            )
            if not desc:
                out.append(PolicyViolation(
                    subject=schema.pointer,
                    detail=f"schema {schema.name or schema.pointer} has no description",
                    location=schema.location,
                ))
    return tuple(out)


RULES: dict[str, RuleSpec] = {
    s.rule: s
    for s in (
        RuleSpec(rule="require_auth", check_id="POLICY001",
                 title="Public operation requires authentication",
                 default_severity=Severity.HIGH, predicate=_require_auth),
        RuleSpec(rule="require_slo", check_id="POLICY002",
                 title="Critical API requires a declared SLO",
                 default_severity=Severity.MEDIUM, predicate=_require_slo),
        RuleSpec(rule="no_wildcard_cors", check_id="POLICY003",
                 title="Wildcard CORS origin not allowed",
                 default_severity=Severity.HIGH, predicate=_no_wildcard_cors),
        RuleSpec(rule="min_deprecation_days", check_id="POLICY004",
                 title="Deprecated API exceeds minimum deprecation period",
                 default_severity=Severity.MEDIUM, predicate=_min_deprecation_days),
        RuleSpec(rule="require_operation_id", check_id="POLICY005",
                 title="Operation requires an operationId",
                 default_severity=Severity.MEDIUM, predicate=_require_operation_id),
        RuleSpec(rule="require_owner", check_id="POLICY006",
                 title="API requires a resolved owner",
                 default_severity=Severity.MEDIUM, predicate=_require_owner),
        RuleSpec(rule="doc_coverage", check_id="POLICY007",
                 title="Documentation coverage opportunity (§189)",
                 default_severity=Severity.INFO, predicate=_doc_coverage),
    )
}
