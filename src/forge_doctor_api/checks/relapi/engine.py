"""RELAPI### check engine (§40-47, §228).

All checks fire only on declared evidence - config files, contract
metadata, observed retries. An absent signal stays UNKNOWN, never an
assumed default (§41, §102).
"""

from __future__ import annotations

from forge_doctor_api.checks.relapi.catalog import BY_ID, RelCheckSpec
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    IdempotencyVerdict,
    RetryPolicy,
)
from forge_doctor_api.reliability.retry import amplification
from forge_doctor_api.reliability.timeout import (
    BudgetVerdict,
    evaluate_timeout_budget,
)


def _finding(
    spec: RelCheckSpec,
    description: str,
    path: str,
    unknowns: tuple[UnknownFact, ...] = (),
    remediation: str | None = None,
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=spec.evidence_kind, source=path, summary=description
            ),
        ),
        source_location=SourceLocation(path=path),
        remediation=remediation,
        unknowns=unknowns,
    )


def run_reliability_checks(
    model: ApiReliabilityModel,
    hops: tuple[str, ...] | None = None,
) -> tuple[Finding, ...]:
    """RELAPI findings over declared reliability evidence.

    `hops` names an explicit path for amplification/budget evaluation
    (e.g. `("gateway", "payments-service")`); without one, amplification
    multiplies all declared policies as a conservative bound and notes
    the hop set is config-derived.
    """
    findings: list[Finding] = []

    scopes = [p.scope for p in model.retry_policies]
    amp = amplification(hops or tuple(sorted(set(scopes))),
                        model.retry_policies)
    if amp.potential_attempts is not None and amp.potential_attempts > 1:
        findings.append(
            _finding(
                BY_ID["RELAPI001"],
                f"declared retries multiply to {amp.potential_attempts} "
                f"potential attempts across {', '.join(amp.hops)} "
                f"(explicit configs only)",
                "(config)",
                remediation="review whether stacked retries are intended; "
                "verify idempotency before allowing amplification",
            )
        )
    elif amp.missing and hops:
        findings.append(
            _finding(
                BY_ID["RELAPI001"],
                "amplification unknown - hops without declared policies: "
                + ", ".join(amp.missing),
                "(config)",
                unknowns=amp.unknowns,
            )
        )

    # RELAPI002: retried scopes lacking any idempotency verdict
    for policy in model.retry_policies:
        idem = next(
            (i for i in model.idempotency if i.subject == policy.scope),
            None,
        )
        if idem is not None and idem.verdict is IdempotencyVerdict.IDEMPOTENT:
            continue
        verdict = idem.verdict if idem else IdempotencyVerdict.UNKNOWN
        findings.append(
            _finding(
                BY_ID["RELAPI002"],
                f"retries declared at '{policy.scope}' with idempotency "
                f"{verdict.value.lower()} - manual review required",
                (policy.location.path if policy.location else "(config)"),
                unknowns=idem.unknowns if idem else (
                    UnknownFact(
                        subject=policy.scope,
                        missing="idempotency evidence (§42 sources)",
                        resolution="idempotency key, contract metadata, "
                        "or handler semantics required before retrying "
                        "is safe",
                    ),
                ),
                remediation="prove idempotency or bound retries before "
                "enabling amplification",
            )
        )

    # RELAPI003: timeout budgets along the declared hop chain (if given)
    if hops:
        timeouts = {t.scope: t.timeout_ms for t in model.timeouts}
        caller_ms = timeouts.get(hops[0])
        downs = tuple((h, timeouts.get(h)) for h in hops[1:])
        if caller_ms is not None or downs:
            budget = evaluate_timeout_budget(hops[0], caller_ms, downs)
            if budget.verdict is BudgetVerdict.IMPOSSIBLE:
                findings.append(
                    _finding(
                        BY_ID["RELAPI003"],
                        f"{hops[0]}: downstream budgets "
                        f"({', '.join(f'{n}={m}ms' for n, m in downs)}) "
                        f"exceed caller timeout {caller_ms}ms even in "
                        "parallel",
                        "(config)",
                    )
                )
            elif budget.verdict is BudgetVerdict.AT_RISK:
                findings.append(
                    _finding(
                        BY_ID["RELAPI003"],
                        f"{hops[0]}: downstream budgets exceed caller "
                        f"timeout {caller_ms}ms if calls run sequentially",
                        "(config)",
                        unknowns=budget.unknowns,
                    )
                )

    # RELAPI004: scopes with timeouts but no deadline-propagation evidence
    if model.timeouts:
        propagated = {t.scope for t in model.timeouts
                      if "stub call" in " ".join(e.summary for e in t.evidence)}
        gap_scopes = sorted({t.scope for t in model.timeouts} - propagated)
        if gap_scopes:
            findings.append(
                _finding(
                    BY_ID["RELAPI004"],
                    "timeout evidence without call-site deadline "
                    f"propagation at: {', '.join(gap_scopes)}",
                    "(config)",
                    unknowns=(
                        UnknownFact(
                            subject="deadline propagation",
                            missing="call-site deadline evidence on the "
                            "s2s/grpc path",
                            resolution="verify callers pass deadlines "
                            "downstream",
                        ),
                    ),
                )
            )

    # RELAPI005: retry or timeout evidence with no circuit breaker
    if (model.retry_policies or model.timeouts) and not model.circuit_breakers:
        findings.append(
            _finding(
                BY_ID["RELAPI005"],
                "retry/timeout evidence exists but no circuit-breaker "
                "configuration was found - candidate",
                "(config)",
                unknowns=(
                    UnknownFact(
                        subject="circuit breakers",
                        missing="declared circuit-breaker config",
                        resolution="CBs may live in mesh/app config not "
                        "provided",
                    ),
                ),
            )
        )

    # RELAPI006/007: health + shutdown evidence absence (candidates)
    if model.retry_policies or model.timeouts or model.circuit_breakers:
        if not model.health_checks:
            findings.append(
                _finding(
                    BY_ID["RELAPI006"],
                    "reliability config exists but no health-check "
                    "evidence - candidate",
                    "(config)",
                    unknowns=(
                        UnknownFact(
                            subject="health checks",
                            missing="declared health-check config",
                            resolution="health checks may live in "
                            "orchestrator config not provided",
                        ),
                    ),
                )
            )
        if not model.shutdown_evidence:
            findings.append(
                _finding(
                    BY_ID["RELAPI007"],
                    "no graceful-shutdown/drain configuration evidence - "
                    "candidate",
                    "(config)",
                    unknowns=(
                        UnknownFact(
                            subject="graceful shutdown",
                            missing="drain/shutdown configuration",
                            resolution="shutdown handling may live in "
                            "platform config not provided",
                        ),
                    ),
                )
            )

    findings.sort(key=lambda f: (f.id, f.description))
    return tuple(findings)


def _retry_for(model: ApiReliabilityModel, caller: str,
               callee: str | None = None) -> RetryPolicy | None:
    """Declared retry binding for `caller` (exact or edge scope)."""
    for p in model.retry_policies:
        if p.scope == caller:
            return p
    if callee is not None:
        edge = f"{caller}->{callee}"
        for p in model.retry_policies:
            if p.scope == edge:
                return p
    for p in sorted(model.retry_policies, key=lambda x: x.scope):
        if p.scope.split("->", 1)[0].strip() == caller:
            return p
    return None


class _Missing:
    pass


_MISSING = _Missing()


def _timeout_for(model: ApiReliabilityModel,
                 scope: str) -> float | _Missing | None:
    for t in model.timeouts:
        if t.scope == scope:
            return t.timeout_ms
    return _MISSING


def run_depth_checks(
    model: ApiReliabilityModel,
    chain_edges: tuple[tuple[str, str], ...],
) -> tuple[Finding, ...]:
    """APIREL### depth checks over evidenced caller->callee edges (spec 062).

    `chain_edges` must come from declared config/runtime evidence
    (gateway routes, CALLS relationships). Name similarity never
    creates a hop — callers pass only evidenced pairs.
    """
    findings: list[Finding] = []
    for caller, callee in sorted(set(chain_edges)):
        edge = f"{caller}->{callee}"

        # APIREL001 - retry amplification on the evidenced edge
        caller_retry = _retry_for(model, caller, callee)
        callee_retry = _retry_for(model, callee)
        if caller_retry is not None and callee_retry is not None:
            ca = caller_retry.max_attempts or 0
            cb = callee_retry.max_attempts or 0
            if ca > 1 and cb > 1:
                findings.append(_finding(
                    BY_ID["APIREL001"],
                    f"{edge}: caller retries {ca}x and callee retries "
                    f"{cb}x - amplification bound {ca * cb} attempts "
                    "on this edge",
                    (caller_retry.location.path if caller_retry.location
                     else "(config)"),
                ))

        # APIREL002 - timeout cascade on the evidenced edge
        caller_ms = _timeout_for(model, caller)
        callee_ms = _timeout_for(model, callee)
        if isinstance(caller_ms, _Missing):
            continue
        if isinstance(callee_ms, _Missing):
            findings.append(_finding(
                BY_ID["APIREL002"],
                f"{edge}: caller timeout {caller_ms}ms declared but "
                "the callee has no declared timeout - cascade bound "
                "is unknown",
                "(config)",
                unknowns=(
                    UnknownFact(
                        subject=edge,
                        missing="callee timeout declaration",
                        resolution="declare a timeout at the callee "
                        "scope to bound the cascade"),
                ),
            ))
        elif caller_ms is not None and callee_ms is not None \
                and caller_ms < callee_ms:
            findings.append(_finding(
                BY_ID["APIREL002"],
                f"{edge}: caller timeout {caller_ms}ms < callee "
                f"timeout {callee_ms}ms - requests cannot complete "
                "within the caller budget",
                "(config)",
            ))
    findings.sort(key=lambda f: (f.id, f.description))
    return tuple(findings)
