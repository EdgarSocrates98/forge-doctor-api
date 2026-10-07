"""§65 change events — derive typed events from diff elements.

Two sources:
- contract diff (`ContractDiff` from `checks.compat`) -> endpoint/schema/auth
  change events;
- config-model diff (reliability, security, version models) ->
  timeout/retry/rate-limit/dependency/version change events. The review note
  requires config-file diffs to surface TIMEOUT_CHANGED/RETRY_CHANGED, not
  just contract diffs.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.openapi import OpenApiProjectModel
from forge_doctor_api.analyzers.version import ApiVersionModel
from forge_doctor_api.change.model import ChangeEvent, ChangeReport, ChangeType
from forge_doctor_api.checks.compat import (
    ChangeSide,
    CompatibilityClass,
    ContractChange,
    ContractDiff,
)
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.reliability.model import ApiReliabilityModel
from forge_doctor_api.security.model import ApiSecurityModel

_KIND_TO_TYPE: dict[str, ChangeType] = {
    "endpoint_added": ChangeType.ENDPOINT_ADDED,
    "endpoint_removed": ChangeType.ENDPOINT_REMOVED,
    "method_removed": ChangeType.METHOD_CHANGED,
    "auth_tightened": ChangeType.AUTH_CHANGED,
    "auth_loosened": ChangeType.AUTH_CHANGED,
}
# Everything else (param/request/response/enum/type/status/content_type
# changes, plus `unresolvable`) is a schema-level change.


def _derived_evidence(change: ContractChange | None, subject: str,
                      detail: str, location: SourceLocation | None) -> tuple[Evidence, ...]:
    return (
        Evidence(
            kind=EvidenceKind.DERIVED,
            source=location.path if location else "semantic-diff",
            summary=detail,
            line=location.line if location else None,
        ),
    )


def _to_event(change: ContractChange) -> ChangeEvent:
    return ChangeEvent(
        type=_KIND_TO_TYPE.get(change.kind, ChangeType.SCHEMA_CHANGED),
        kind=change.kind,
        classification=change.classification,
        side=change.side,
        subject=change.subject,
        path=change.path,
        detail=change.detail,
        before=change.before,
        after=change.after,
        location=change.location,
        evidence=_derived_evidence(change, change.subject, change.detail, change.location),
        unknowns=(
            UnknownFact(
                subject=change.subject,
                missing=change.detail,
                resolution="resolve the diff element so the change can be classified",
            ),
        )
        if change.classification is CompatibilityClass.UNKNOWN
        else (),
    )


def contract_events(diff: ContractDiff) -> tuple[ChangeEvent, ...]:
    """Map a contract diff to typed events, deterministically ordered."""
    events = [_to_event(c) for c in diff.changes]
    events.sort(key=lambda e: (e.type.value, e.subject, e.path or "", e.kind))
    return tuple(events)


# ---------------------------------------------------------------------------
# Config-model diffs


def _config_event(
    type: ChangeType,
    kind: str,
    classification: CompatibilityClass,
    subject: str,
    detail: str,
    *,
    before: str | None = None,
    after: str | None = None,
    location: SourceLocation | None = None,
    unknown_ms: bool = False,
) -> ChangeEvent:
    return ChangeEvent(
        type=type,
        kind=kind,
        classification=classification,
        side=ChangeSide.META,
        subject=subject,
        detail=detail,
        before=before,
        after=after,
        location=location,
        evidence=_derived_evidence(None, subject, detail, location),
        unknowns=(
            UnknownFact(
                subject=subject,
                missing=detail,
                resolution="declare the missing config value so the change can be classified",
            ),
        )
        if unknown_ms or classification is CompatibilityClass.UNKNOWN
        else (),
    )


def _timeout_events(old: ApiReliabilityModel, new: ApiReliabilityModel) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    om = {t.scope: t for t in old.timeouts}
    nm = {t.scope: t for t in new.timeouts}
    for scope in sorted(set(om) | set(nm)):
        o, n = om.get(scope), nm.get(scope)
        if o is None and n is not None:
            events.append(_config_event(
                ChangeType.TIMEOUT_CHANGED, "timeout_added",
                CompatibilityClass.POTENTIALLY_BREAKING, scope,
                f"timeout policy added for `{scope}` ({n.timeout_ms} ms)",
                after=str(n.timeout_ms), location=n.location,
                unknown_ms=n.timeout_ms is None,
            ))
        elif n is None and o is not None:
            events.append(_config_event(
                ChangeType.TIMEOUT_CHANGED, "timeout_removed",
                CompatibilityClass.POTENTIALLY_BREAKING, scope,
                f"timeout policy removed for `{scope}` (was {o.timeout_ms} ms)",
                before=str(o.timeout_ms), location=o.location,
            ))
        elif o is not None and n is not None and o.timeout_ms != n.timeout_ms:
            if o.timeout_ms is None or n.timeout_ms is None:
                cls = CompatibilityClass.UNKNOWN
            else:
                cls = (
                    CompatibilityClass.POTENTIALLY_BREAKING
                    if n.timeout_ms < o.timeout_ms
                    else CompatibilityClass.NON_BREAKING
                )
            events.append(_config_event(
                ChangeType.TIMEOUT_CHANGED, "timeout_ms_changed", cls, scope,
                f"timeout for `{scope}` changed {o.timeout_ms} ms -> {n.timeout_ms} ms",
                before=str(o.timeout_ms), after=str(n.timeout_ms),
                location=n.location,
                unknown_ms=cls is CompatibilityClass.UNKNOWN,
            ))
    return events


def _retry_events(old: ApiReliabilityModel, new: ApiReliabilityModel) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    om = {p.scope: p for p in old.retry_policies}
    nm = {p.scope: p for p in new.retry_policies}
    for scope in sorted(set(om) | set(nm)):
        o, n = om.get(scope), nm.get(scope)
        if o is None and n is not None:
            events.append(_config_event(
                ChangeType.RETRY_CHANGED, "retry_added",
                CompatibilityClass.POTENTIALLY_BREAKING, scope,
                f"retry policy added for `{scope}` (max_attempts={n.max_attempts})",
                after=str(n.max_attempts), location=n.location,
            ))
        elif n is None and o is not None:
            events.append(_config_event(
                ChangeType.RETRY_CHANGED, "retry_removed",
                CompatibilityClass.POTENTIALLY_BREAKING, scope,
                f"retry policy removed for `{scope}` (was max_attempts={o.max_attempts})",
                before=str(o.max_attempts), location=o.location,
            ))
        elif o is not None and n is not None:
            changed = (
                o.max_attempts != n.max_attempts
                or o.backoff != n.backoff
                or o.jitter != n.jitter
                or o.retryable_statuses != n.retryable_statuses
            )
            if not changed:
                continue
            if o.max_attempts != n.max_attempts:
                if o.max_attempts is None or n.max_attempts is None:
                    cls = CompatibilityClass.UNKNOWN
                else:
                    cls = (
                        CompatibilityClass.POTENTIALLY_BREAKING
                        if n.max_attempts > o.max_attempts
                        else CompatibilityClass.NON_BREAKING
                    )
                detail = (
                    f"retry policy for `{scope}` changed "
                    f"max_attempts {o.max_attempts} -> {n.max_attempts}"
                )
            else:
                cls = CompatibilityClass.UNKNOWN
                detail = f"retry policy for `{scope}` changed (backoff/jitter/statuses)"
            events.append(_config_event(
                ChangeType.RETRY_CHANGED, "retry_changed", cls, scope, detail,
                before=str(o.max_attempts), after=str(n.max_attempts),
                location=n.location,
            ))
    return events


def _rate_limit_events(old: ApiSecurityModel, new: ApiSecurityModel) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    om = {p.scope: p for p in old.rate_limits}
    nm = {p.scope: p for p in new.rate_limits}
    for scope in sorted(set(om) | set(nm)):
        o, n = om.get(scope), nm.get(scope)
        if o is None and n is not None:
            events.append(_config_event(
                ChangeType.RATE_LIMIT_CHANGED, "rate_limit_added",
                CompatibilityClass.POTENTIALLY_BREAKING, scope,
                f"rate limit added for `{scope}` ({n.limit}/{n.window or 'window'})",
                after=str(n.limit), location=n.location,
            ))
        elif n is None and o is not None:
            events.append(_config_event(
                ChangeType.RATE_LIMIT_CHANGED, "rate_limit_removed",
                CompatibilityClass.NON_BREAKING, scope,
                f"rate limit removed for `{scope}` (was {o.limit})",
                before=str(o.limit), location=o.location,
            ))
        elif o is not None and n is not None and (
            o.limit != n.limit or o.window != n.window or o.burst != n.burst
        ):
            if o.limit is None or n.limit is None or o.limit == n.limit:
                cls = CompatibilityClass.UNKNOWN
            else:
                cls = (
                    CompatibilityClass.POTENTIALLY_BREAKING
                    if n.limit < o.limit
                    else CompatibilityClass.NON_BREAKING
                )
            events.append(_config_event(
                ChangeType.RATE_LIMIT_CHANGED, "rate_limit_changed", cls, scope,
                f"rate limit for `{scope}` changed {o.limit} -> {n.limit} "
                f"(window {o.window} -> {n.window})",
                before=str(o.limit), after=str(n.limit), location=n.location,
            ))
    return events


def _dependency_events(old: ApiSecurityModel, new: ApiSecurityModel) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    om = {a.host: a for a in old.external_apis}
    nm = {a.host: a for a in new.external_apis}
    for host in sorted(set(om) | set(nm)):
        o, n = om.get(host), nm.get(host)
        if o is None and n is not None:
            events.append(_config_event(
                ChangeType.DEPENDENCY_CHANGED, "dependency_added",
                CompatibilityClass.NON_BREAKING, host,
                f"external dependency `{host}` declared",
                after=host, location=None,
            ))
        elif n is None and o is not None:
            events.append(_config_event(
                ChangeType.DEPENDENCY_CHANGED, "dependency_removed",
                CompatibilityClass.POTENTIALLY_BREAKING, host,
                f"external dependency `{host}` no longer declared",
                before=host, location=None,
            ))
        elif o is not None and n is not None and (
            o.timeout_ms != n.timeout_ms
            or o.has_retry != n.has_retry
            or o.has_auth != n.has_auth
        ):
            events.append(_config_event(
                ChangeType.DEPENDENCY_CHANGED, "dependency_changed",
                CompatibilityClass.UNKNOWN, host,
                f"external dependency `{host}` configuration changed",
                before=host, after=host, location=None,
            ))
    return events


def _version_events(old: ApiVersionModel, new: ApiVersionModel,
                    old_doc: OpenApiProjectModel | None,
                    new_doc: OpenApiProjectModel | None) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    old_ids = {(v.mechanism.value, v.identifier) for v in old.versions}
    new_ids = {(v.mechanism.value, v.identifier) for v in new.versions}
    for mech, ident in sorted(old_ids - new_ids):
        events.append(_config_event(
            ChangeType.VERSION_CHANGED, "version_removed",
            CompatibilityClass.POTENTIALLY_BREAKING, ident,
            f"version marker `{ident}` ({mech}) removed",
            before=ident,
        ))
    for mech, ident in sorted(new_ids - old_ids):
        events.append(_config_event(
            ChangeType.VERSION_CHANGED, "version_added",
            CompatibilityClass.NON_BREAKING, ident,
            f"version marker `{ident}` ({mech}) added",
            after=ident,
        ))
    if old_doc is not None and new_doc is not None:
        old_versions = sorted(
            d.api_version for d in old_doc.documents if d.api_version is not None
        )
        new_versions = sorted(
            d.api_version for d in new_doc.documents if d.api_version is not None
        )
        if old_versions != new_versions:
            title = (
                new_doc.documents[0].title or old_doc.documents[0].title
                if new_doc.documents or old_doc.documents
                else "api"
            ) or "api"
            events.append(_config_event(
                ChangeType.VERSION_CHANGED, "api_version_changed",
                CompatibilityClass.NON_BREAKING, title,
                f"document version {old_versions} -> {new_versions}",
                before=str(old_versions), after=str(new_versions),
                location=new_doc.documents[0].location if new_doc.documents else None,
            ))
    return events


def config_events(
    old_reliability: ApiReliabilityModel | None,
    new_reliability: ApiReliabilityModel | None,
    old_security: ApiSecurityModel | None,
    new_security: ApiSecurityModel | None,
    old_version: ApiVersionModel | None,
    new_version: ApiVersionModel | None,
    old_doc: OpenApiProjectModel | None = None,
    new_doc: OpenApiProjectModel | None = None,
) -> tuple[ChangeEvent, ...]:
    """Diff config-plane models -> TIMEOUT/RETRY/RATE_LIMIT/DEPENDENCY/VERSION events."""
    events: list[ChangeEvent] = []
    if old_reliability is not None or new_reliability is not None:
        rel_o = old_reliability or ApiReliabilityModel()
        rel_n = new_reliability or ApiReliabilityModel()
        events.extend(_timeout_events(rel_o, rel_n))
        events.extend(_retry_events(rel_o, rel_n))
    if old_security is not None or new_security is not None:
        sec_o = old_security or ApiSecurityModel()
        sec_n = new_security or ApiSecurityModel()
        events.extend(_rate_limit_events(sec_o, sec_n))
        events.extend(_dependency_events(sec_o, sec_n))
    if old_version is not None or new_version is not None:
        events.extend(_version_events(
            old_version or ApiVersionModel(),
            new_version or ApiVersionModel(),
            old_doc, new_doc,
        ))
    events.sort(key=lambda e: (e.type.value, e.subject, e.path or "", e.kind))
    return tuple(events)


def change_report(diff: ContractDiff, config: tuple[ChangeEvent, ...] = ()) -> ChangeReport:
    """Assemble the §66 report: contract events + config events, deterministic order."""
    events = (*contract_events(diff), *config)
    ordered = tuple(sorted(events, key=lambda e: (e.type.value, e.subject, e.path or "", e.kind)))
    return ChangeReport(events=ordered, diff=diff)
