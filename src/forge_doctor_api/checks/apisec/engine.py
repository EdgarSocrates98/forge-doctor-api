"""APISEC### check engine (§50, §229).

Findings carry the §49 four-level classification in their description
prefix (`[candidate]` / `[configuration risk]` / ...). Static analysis
NEVER produces "vulnerability confirmed" (§50, §229). Sensitive
categories come only from explicit metadata (§124).
"""

from __future__ import annotations

import re
from typing import Any

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
)
from forge_doctor_api.checks.apisec.catalog import BY_ID, SecCheckSpec
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.security.knowledge import check_to_owasp
from forge_doctor_api.security.model import ApiSecurityModel
from forge_doctor_api.security.scan import normalize_route_path, op_requires_auth

_OBJECT_ID_RE = re.compile(
    r"^(id|uuid|guid|pk|[a-z0-9_]*_id|[a-z0-9]*Id|[a-z0-9]*Uuid)$"
)
_ADMIN_RE = re.compile(r"(^|[/_.-])admin([/_.-]|$)", re.IGNORECASE)
_SENSITIVE_FIELD_NAMES = frozenset({
    "password", "passwd", "secret", "token", "access_token",
    "refresh_token", "api_key", "apikey", "private_key", "ssn",
    "social_security_number", "credit_card", "card_number", "cvv",
    "iban", "account_number", "pin",
})

_URL_PARAM_RE = re.compile(
    r"^(url|uri|endpoint|target|callback|webhook|redirect(_uri|_url)?|"
    r"feed|fetch|image_url|avatar_url|source|dest|destination|link|site)$",
    re.IGNORECASE,
)


def _finding(
    spec: SecCheckSpec,
    description: str,
    path: str,
    line: int | None = None,
    unknowns: tuple[UnknownFact, ...] = (),
    remediation: str | None = None,
) -> Finding:
    cats = check_to_owasp(spec.id)
    label = f"[{spec.finding_class.value}]"
    owasp = f" ({', '.join(cats)})" if cats else ""
    desc = f"{label}{owasp} {description}"
    return Finding(
        id=spec.id,
        title=spec.title,
        description=desc,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=spec.evidence_kind, source=path, summary=description,
                line=line,
            ),
        ),
        source_location=SourceLocation(path=path, line=line),
        remediation=remediation,
        unknowns=unknowns,
    )


def _op_params(
    model: OpenApiProjectModel, op: OpenApiOperation
) -> list[Any]:
    by_ptr = {p.pointer: p for p in model.parameters}
    return [by_ptr[p] for p in op.parameter_pointers if p in by_ptr]


def _path_id_params(model: OpenApiProjectModel,
                    op: OpenApiOperation) -> list[str]:
    return [
        p.name
        for p in _op_params(model, op)
        if p.location_in == "path" and p.name and _OBJECT_ID_RE.match(p.name)
    ]


def _anonymous_ok(model: OpenApiProjectModel, op: OpenApiOperation) -> bool:
    req, _ = op_requires_auth(model, op)
    return req is False


def _returns_collection(
    model: OpenApiProjectModel, op: OpenApiOperation
) -> bool:
    """True when a 2xx response schema resolves to a JSON array.

    Requires schema evidence - a bare GET path is not enough (avoids
    singleton false positives like `/admin/panel`).
    """
    resp_by_ptr = {r.pointer: r for r in model.responses}
    schemas = {s.name: s for s in model.schemas}
    for ptr in op.response_pointers:
        resp = resp_by_ptr.get(ptr)
        if resp is None or not (resp.status or "").startswith("2"):
            continue
        comp = resp.component_name
        if comp and comp in schemas:
            body = schemas[comp].content
            if isinstance(body, dict) and body.get("type") == "array":
                return True
            if isinstance(body, dict) and "items" in body:
                return True
        # inline shape tokens carrying array-ness
        for shape in resp.schema_shapes:
            if "type:array" in shape:
                return True
    return False


def _sensitive_ops(model: OpenApiProjectModel) -> set[str]:
    """§124: only explicit `x-` classification metadata marks an op."""
    out: set[str] = set()
    for ext in model.extensions:
        if ext.name.lower() in {
            "x-sensitive", "x-pii", "x-classification",
            "x-data-classification", "x-sensitivity",
        } and ext.value not in (None, False, ""):
            out.add(ext.owner_pointer)
    return out


def run_security_checks(
    model: ApiSecurityModel,
    openapi: OpenApiProjectModel | None = None,
) -> tuple[Finding, ...]:
    """APISEC001-010 over aggregated passive evidence."""
    findings: list[Finding] = []

    if openapi is not None:
        sensitive_ptrs = _sensitive_ops(openapi)
        ownership_ops = {
            a.operation for a in model.authorization if a.ownership_check
        }
        authz_ops = {
            a.operation for a in model.authorization
            if a.roles or a.scopes or a.claims
        }
        pag_by_op = {p.operation: p for p in model.pagination}
        resp_components: set[str] = set()
        for r in openapi.responses:
            if r.component_name:
                resp_components.add(r.component_name)
            for shape in r.schema_shapes:
                if shape.startswith("ref:#/components/schemas/"):
                    resp_components.add(
                        shape.rsplit("/", 1)[-1]
                    )

        for op in openapi.operations:
            # APISEC001 - object-id path param + no object-level authz
            id_params = _path_id_params(openapi, op)
            if id_params and op.identity not in ownership_ops \
                    and op.identity not in authz_ops:
                findings.append(
                    _finding(
                        BY_ID["APISEC001"],
                        f"{op.method.upper()} {op.path}: object-id "
                        f"parameter(s) {', '.join(id_params)} with no "
                        "authorization evidence - BOLA risk candidate, "
                        "manual review required",
                        op.location.path, op.location.line,
                        unknowns=(
                            UnknownFact(
                                subject=op.identity,
                                missing="object-level authorization "
                                "evidence (ownership check, roles, "
                                "scopes)",
                                resolution="declare x-ownership-check / "
                                "x-roles / security scopes, or provide "
                                "impl authz evidence",
                            ),
                        ),
                        remediation="verify caller owns the referenced "
                        "object before returning it",
                    )
                )

            # APISEC002 - admin-marked op without explicit authz
            if (_ADMIN_RE.search(op.path) or (
                op.operation_id and _ADMIN_RE.search(op.operation_id)
            )) and op.identity not in authz_ops:
                    findings.append(
                        _finding(
                            BY_ID["APISEC002"],
                            f"{op.method.upper()} {op.path}: admin-marked "
                            "operation without explicit roles/scopes - "
                            "function-level authz candidate",
                            op.location.path, op.location.line,
                            unknowns=(
                                UnknownFact(
                                    subject=op.identity,
                                    missing="explicit authorization "
                                    "metadata for the admin surface",
                                    resolution="declare x-roles/x-scopes "
                                    "or gateway policy covering this op",
                                ),
                            ),
                        )
                    )

            # APISEC003 - anonymous + explicitly sensitive
            if _anonymous_ok(openapi, op) and op.pointer in sensitive_ptrs:
                findings.append(
                    _finding(
                        BY_ID["APISEC003"],
                        f"{op.method.upper()} {op.path}: anonymous access "
                        "allowed on an explicitly sensitive-marked "
                        "operation - authentication candidate",
                        op.location.path, op.location.line,
                        remediation="require authentication for the "
                        "classified operation",
                    )
                )

            # APISEC005 - public op without rate-limit coverage
            if _anonymous_ok(openapi, op):
                covered = any(
                    r.scope == "*" or r.scope in op.path
                    or normalize_route_path(r.scope) == normalize_route_path(op.path)
                    or op.path.startswith(r.scope.rstrip("/"))
                    for r in model.rate_limits
                )
                if (model.rate_limits and not covered) or not model.rate_limits:
                    findings.append(
                        _finding(
                            BY_ID["APISEC005"],
                            f"{op.method.upper()} {op.path}: public "
                            "operation with no rate-limit evidence - "
                            "candidate",
                            op.location.path, op.location.line,
                            unknowns=(
                                UnknownFact(
                                    subject=op.identity,
                                    missing="rate-limit policy",
                                    resolution="rate limits may live in "
                                    "gateway config not provided",
                                ),
                            ),
                        )
                    )

            # APISEC006 - unbounded list endpoint (§118-119)
            pag = pag_by_op.get(op.identity)
            if (
                op.method.lower() == "get"
                and _returns_collection(openapi, op)
                and (pag is None or not pag.bounded)
            ):
                findings.append(
                    _finding(
                        BY_ID["APISEC006"],
                        f"GET {op.path}: list-returning endpoint without "
                        "a bounded pagination/limit parameter - "
                        "unrestricted resource candidate",
                        op.location.path, op.location.line,
                        remediation="declare a limit/pagination parameter "
                        "or a rate-limit policy",
                    )
                )

            # APISEC007 - URL-shaped input parameter (SSRF candidate)
            url_params = [
                p.name
                for p in _op_params(openapi, op)
                if p.name and _URL_PARAM_RE.match(p.name)
                and p.location_in in {"query", "header"}
            ]
            if url_params:
                findings.append(
                    _finding(
                        BY_ID["APISEC007"],
                        f"{op.method.upper()} {op.path}: URL-shaped "
                        f"parameter(s) {', '.join(url_params)} - unsafe "
                        "outbound consumption candidate",
                        op.location.path, op.location.line,
                        unknowns=(
                            UnknownFact(
                                subject=op.identity,
                                missing="server-side fetch behavior",
                                resolution="confirm whether the value "
                                "feeds an outbound request; if so, "
                                "constrain allowed hosts",
                            ),
                        ),
                    )
                )

            # APISEC009 - deprecated still reachable
            if op.deprecated:
                findings.append(
                    _finding(
                        BY_ID["APISEC009"],
                        f"{op.method.upper()} {op.path}: deprecated "
                        "operation still documented as reachable",
                        op.location.path, op.location.line,
                    )
                )

        # APISEC008 - explicitly classified property in a response schema
        for c in model.classifications:
            schema_name = c.subject.split(".", 1)[0]
            if schema_name in resp_components:
                findings.append(
                    _finding(
                        BY_ID["APISEC008"],
                        f"property {c.subject} classified {c.category.value} "
                        "appears in a response schema - exposure candidate",
                        c.evidence[0].source if c.evidence else "(contract)",
                    )
                )

        # APISEC011 - auth-coverage chain: global <-> op inheritance
        # (spec 061). An op inheriting global security needs no finding;
        # an op declaring `security:` whose requirements cannot be
        # resolved, or an op with no security evidence anywhere, is
        # UNKNOWN - never PASS, never FAIL.
        global_reqs = tuple(
            r for r in openapi.security_requirements
            if r.owner_pointer == "")
        declared_schemes = {s.name for s in openapi.security_schemes}
        for op in openapi.operations:
            op_reqs = tuple(
                r for r in openapi.security_requirements
                if r.owner_pointer == op.pointer)
            requires, scopes = op_requires_auth(openapi, op)
            global_schemes = sorted(
                {s.name for r in global_reqs for s in r.schemes})
            unresolvable = [
                s.name for r in op_reqs for s in r.schemes
                if s.name not in declared_schemes]
            chain = (
                f"global_schemes={global_schemes} "
                f"op_security={op.has_security} "
                f"op_reqs={len(op_reqs)} scopes={list(scopes)} "
                f"unresolvable={unresolvable}"
            )
            if op.has_security and global_reqs and (
                    not op_reqs or unresolvable):
                # declared op-level security that does not resolve to
                # any requirement - ambiguous override
                findings.append(_finding(
                    BY_ID["APISEC011"],
                    f"{op.method.upper()} {op.path}: declares "
                    "operation-level security but no requirement "
                    f"resolves through the chain ({chain})",
                    op.location.path, op.location.line,
                    unknowns=(
                        UnknownFact(
                            subject=op.identity,
                            missing="resolvable operation security "
                            "requirement",
                            resolution="the op-level security list must "
                            "name declared schemes, or be [] for "
                            "anonymous"),
                    ),
                ))
            elif requires is None and not global_reqs:
                findings.append(_finding(
                    BY_ID["APISEC011"],
                    f"{op.method.upper()} {op.path}: no security "
                    "evidence at any level - effective authentication "
                    f"is unknown ({chain})",
                    op.location.path, op.location.line,
                    unknowns=(
                        UnknownFact(
                            subject=op.identity,
                            missing="global or operation security "
                            "requirement",
                            resolution="declare security schemes and "
                            "requirements, or gateway auth evidence"),
                    ),
                ))

        # APISEC012 - sensitive-named schema field, no protection
        # evidence (spec 061). Name-only + LOW confidence; declared
        # redaction/protection fields suppress the finding.
        classified = {c.subject for c in model.classifications}
        for schema in openapi.schemas:
            body = schema.content
            if not isinstance(body, dict):
                continue
            props = body.get("properties")
            if not isinstance(props, dict):
                continue
            for fname, fbody in sorted(props.items()):
                if fname.lower() not in _SENSITIVE_FIELD_NAMES:
                    continue
                if not isinstance(fbody, dict):
                    fbody = {}
                protected = (
                    fbody.get("writeOnly") is True
                    or fbody.get("format") == "password"
                    or any(str(k).lower().startswith("x-") and
                           "redact" in str(k).lower()
                           for k in fbody)
                    or f"{schema.name}.{fname}" in classified
                )
                if protected:
                    continue
                findings.append(_finding(
                    BY_ID["APISEC012"],
                    f"{schema.name}.{fname}: field name matches the "
                    "sensitive-name list with no declared protection "
                    "evidence - candidate",
                    schema.location.path, schema.location.line,
                    unknowns=(
                        UnknownFact(
                            subject=f"{schema.name}.{fname}",
                            missing="protection evidence (writeOnly, "
                            "x-redact, classification)",
                            resolution="mark the field writeOnly/"
                            "x-redact/classified, or accept exposure"),
                    ),
                ))

    # APISEC013 - auth chain break (spec 079): a chain record is
    # complete when declared contract security lands on an enforcement
    # plane; chain_complete=False covers both directions of a break.
    for link in model.auth_chain:
        if link.chain_complete is not False:
            continue
        src = link.evidence_refs[0] if link.evidence_refs else None
        if link.scheme_declared is not None:
            desc = (
                f"{link.operation}: contract declares security "
                f"({link.scheme_declared}) but the enforcement planes "
                "show none - declared-but-unenforced auth chain break"
            )
            missing = "implementation/gateway enforcement evidence for " \
                "the declared scheme"
        else:
            desc = (
                f"{link.operation}: "
                f"{link.enforcement_point} enforcement evidence with no "
                "contract security declaration - enforced-but-undeclared "
                "auth chain break"
            )
            missing = "contract security requirement matching the " \
                "observed enforcement"
        findings.append(_finding(
            BY_ID["APISEC013"], desc,
            src.source if src else "(contract)",
            src.line if src else None,
            unknowns=(
                UnknownFact(
                    subject=link.operation,
                    missing=missing,
                    resolution="join contract scheme, applied scope, and "
                    "enforcement point by declared identifiers, or "
                    "declare the operation anonymous",
                ),
            ),
        ))

    # APISEC004 - wildcard CORS
    for cors in model.cors:
        if cors.wildcard:
            creds = " with credentials" if cors.credentials else ""
            findings.append(
                _finding(
                    BY_ID["APISEC004"],
                    f"{cors.scope}: CORS allows any origin{creds}",
                    cors.location.path if cors.location else "(config)",
                    cors.location.line if cors.location else None,
                )
            )

    # APISEC010 - external dependency without timeout/auth evidence
    for ext in model.external_apis:
        gaps = [
            g
            for g, ok in (
                ("timeout", ext.timeout_ms is not None),
                ("auth", bool(ext.has_auth)),
            )
            if not ok
        ]
        if gaps:
            findings.append(
                _finding(
                    BY_ID["APISEC010"],
                    f"external api {ext.host}: no declared "
                    f"{'/'.join(gaps)} evidence - unsafe-consumption "
                    "configuration risk",
                    ext.evidence[0].source if ext.evidence else "(config)",
                    unknowns=(
                        UnknownFact(
                            subject=ext.host,
                            missing=f"declared {'/'.join(gaps)} config",
                            resolution="record timeout/auth on the "
                            "external dependency",
                        ),
                    ),
                )
            )

    # Webhook evidence gaps - attached as candidates under APISEC010 only
    # when clearly an outbound-consumer risk; otherwise stay in the model.

    findings.sort(key=lambda f: (f.id, f.description))
    return tuple(findings)
