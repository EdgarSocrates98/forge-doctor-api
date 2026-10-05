"""Passive security evidence scan (§48-57, §115-120, §124).

Aggregates three evidence planes:

- contract: OpenAPI security schemes/requirements, operation
  extensions, parameters, webhooks, deprecated ops;
- implementation: framework auth evidence (e.g. FastAPI `Security`);
- configuration: CORS / rate-limit / TLS / gateway-authz / external-API
  blocks in YAML/JSON plus `CORSMiddleware`-style Python call sites.

Nothing here asserts a vulnerability - it only assembles evidence. The
APISEC engine classifies candidates vs configuration risks (§49-50).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
)
from forge_doctor_api.analyzers.routes.model import RouteModel, RouteScan
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.security.model import (
    ApiSecurityModel,
    AuthChainLink,
    AuthDrift,
    AuthenticationScheme,
    AuthorizationPolicy,
    AuthSchemeType,
    CorsPolicy,
    DataCategory,
    DataClassification,
    ExternalApi,
    PaginationKind,
    PaginationModel,
    RateLimitPolicy,
    SensitiveBusinessFlow,
    TlsEvidence,
    WebhookModel,
)

_CONFIG_SUFFIXES = {".yaml", ".yml", ".json"}

_OBJECT_ID_RE = re.compile(
    r"^(id|uuid|guid|pk|key|[a-z0-9_]*_?id|[a-z0-9]*Id|[a-z0-9]*Uuid)$"
)
_ADMIN_RE = re.compile(r"(^|[/_.-])admin([/_.-]|$)", re.IGNORECASE)
_URL_PARAM_RE = re.compile(
    r"^(url|uri|endpoint|target|callback|webhook|redirect(_uri|_url)?|"
    r"feed|fetch|image_url|avatar_url|source|dest|destination|link|site)$",
    re.IGNORECASE,
)
_LIMIT_PARAMS = {"limit", "per_page", "page_size", "pagesize", "max_results",
                 "maxresults", "top", "count", "size"}
_OFFSET_PARAMS = {"offset", "page", "p", "start", "skip"}
_CURSOR_PARAMS = {"cursor", "after", "before", "next", "continuation"}
_TOKEN_PARAMS = {"page_token", "pagetoken", "continuation_token",
                 "next_token", "token"}

_SENSITIVE_EXT = {
    "x-sensitive", "x-pii", "x-classification", "x-data-classification",
    "x-sensitivity",
}
_FLOW_EXT = {"x-sensitive-flow", "x-business-flow", "x-protected-flow"}

_CORS_KEYS = ("cors", "cors_policy", "corsPolicy", "cors_configuration",
              "corsConfiguration")
_RL_KEYS = ("rate_limit", "rateLimit", "ratelimit", "rate_limits",
            "limit_req", "throttle", "throttling")
_TLS_KEYS = ("tls", "ssl", "mtls", "client_certificate",
             "require_client_certificate", "transport_security")
_GW_AUTHZ_KEYS = ("authorization", "rbac", "ext_authz", "authz",
                  "authorization_policy", "access_policy")
_WEBHOOK_KEYS = ("webhooks", "webhook", "callbacks_config")
_EXT_API_KEYS = ("external_apis", "externalApis", "external_api",
                 "third_party_apis", "upstream_services", "outbound")
_FLOW_KEYS = ("sensitive_flows", "business_flows", "protected_flows")

_NAME_KEYS = ("scope", "name", "service", "route", "cluster", "operation")

_PY_CORS_RE = re.compile(r"CORSMiddleware\b")
_PY_ALLOW_ORIGINS = re.compile(r"allow_origins\s*=\s*(\[[^\]]*\]|\*|\"[^\"]*\")")
_PY_ALLOW_CREDS = re.compile(r"allow_credentials\s*=\s*(True|False)")


def _ev(kind: EvidenceKind, path: str, summary: str,
        line: int | None = None) -> tuple[Evidence, ...]:
    return (Evidence(kind=kind, source=path, summary=summary, line=line),)


def _line_of(text: str, needle: str) -> int | None:
    i = text.find(needle)
    return text[:i].count("\n") + 1 if i >= 0 else None


def _nearest(node: Any, trail: tuple[str, ...]) -> str | None:
    if isinstance(node, dict):
        for k in _NAME_KEYS:
            v = node.get(k)
            if isinstance(v, str) and v:
                return v
    for k in reversed(trail):
        if k not in _CORS_KEYS + _RL_KEYS + _TLS_KEYS + _GW_AUTHZ_KEYS:
            return k
    return None


def _as_str_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(s.strip() for s in value.split(",") if s.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


# ---------- contract plane ----------


def _scheme_type(scheme_type: str | None, scheme: str | None,
                 bearer: str | None) -> AuthSchemeType:
    t = (scheme_type or "").lower()
    s = (scheme or "").lower()
    if t == "oauth2":
        return AuthSchemeType.OAUTH2
    if t == "openidconnect":
        return AuthSchemeType.OIDC
    if t == "mutualtls":
        return AuthSchemeType.MTLS
    if t == "apikey":
        return AuthSchemeType.API_KEY
    if t == "http":
        if s == "basic":
            return AuthSchemeType.BASIC
        if s == "bearer":
            return AuthSchemeType.JWT if (bearer or "").upper() == "JWT" \
                else AuthSchemeType.CUSTOM
        return AuthSchemeType.CUSTOM
    return AuthSchemeType.UNKNOWN if not t else AuthSchemeType.CUSTOM


def contract_schemes(model: OpenApiProjectModel) -> tuple[AuthenticationScheme, ...]:
    return tuple(
        AuthenticationScheme(
            name=s.name,
            type=_scheme_type(s.type, s.scheme, s.bearer_format),
            plane="contract",
            location_in=s.location_in,
            parameter_name=s.parameter_name,
            evidence=_ev(
                EvidenceKind.STATIC, s.location.path,
                f"security scheme {s.name}", s.location.line,
            ),
        )
        for s in sorted(model.security_schemes, key=lambda x: x.name)
    )


def op_requires_auth(model: OpenApiProjectModel,
                     op: OpenApiOperation) -> tuple[bool | None, tuple[str, ...]]:
    """Effective security for an operation.

    Returns (requires_auth, scopes). `requires_auth` is:
      True  - all alternatives name schemes
      False - anonymous allowed (`security: []` or empty requirement)
      None  - no security evidence anywhere
    """
    reqs = [
        r for r in model.security_requirements
        if r.owner_pointer == op.pointer
    ]
    if not op.has_security:
        reqs = [
            r for r in model.security_requirements
            if r.owner_pointer == ""
        ]
    elif not reqs:
        # op declared `security: []` -> anonymous allowed
        return False, ()
    if not reqs:
        return None, ()
    scopes = tuple(sorted({s for r in reqs for u in r.schemes
                           for s in u.scopes}))
    if any(not r.schemes for r in reqs):
        return False, scopes
    return True, scopes


def contract_authz(model: OpenApiProjectModel) -> tuple[AuthorizationPolicy, ...]:
    """§52 policies from requirement scopes + `x-` authorization metadata."""
    out: list[AuthorizationPolicy] = []
    for op in model.operations:
        ext_roles: list[str] = []
        ext_scopes: list[str] = []
        ext_claims: list[str] = []
        ownership: bool | None = None
        for ext in model.extensions:
            if ext.owner_pointer != op.pointer:
                continue
            name = ext.name.lower()
            val = ext.value
            if name in {"x-roles", "x-role"}:
                ext_roles.extend(_as_str_list(val))
            elif name in {"x-scopes", "x-scope"}:
                ext_scopes.extend(_as_str_list(val))
            elif name in {"x-claims", "x-required-claims"}:
                ext_claims.extend(_as_str_list(val))
            elif name in {"x-ownership-check", "x-owner-check"}:
                ownership = bool(val)
            elif name in {"x-authorization", "x-authz"} and isinstance(val, dict):
                ext_roles.extend(_as_str_list(val.get("roles")))
                ext_scopes.extend(_as_str_list(val.get("scopes")))
                ext_claims.extend(_as_str_list(val.get("claims")))
                if "ownership_check" in val or "ownershipCheck" in val:
                    ownership = bool(
                        val.get("ownership_check", val.get("ownershipCheck"))
                    )
        _, scopes = op_requires_auth(model, op)
        all_scopes = tuple(sorted(set(scopes) | set(ext_scopes)))
        if ext_roles or all_scopes or ext_claims or ownership is not None:
            out.append(
                AuthorizationPolicy(
                    operation=op.identity,
                    roles=tuple(sorted(set(ext_roles))),
                    scopes=all_scopes,
                    claims=tuple(sorted(set(ext_claims))),
                    ownership_check=ownership,
                    plane="contract",
                    evidence=_ev(
                        EvidenceKind.STATIC, op.location.path,
                        f"authorization evidence on {op.identity}",
                        op.location.line,
                    ),
                )
            )
    return tuple(sorted(out, key=lambda p: p.operation))


def contract_webhooks(model: OpenApiProjectModel) -> tuple[WebhookModel, ...]:
    out: list[WebhookModel] = []
    for wh in model.webhooks:
        flags: dict[str, bool | None] = {
            "signature_verification": None,
            "replay_protection": None,
            "idempotency": None,
            "retry": None,
        }
        for ext in model.extensions:
            if not ext.owner_pointer.startswith(wh.pointer):
                continue
            n = ext.name.lower()
            if "signature" in n:
                flags["signature_verification"] = bool(ext.value)
            elif "replay" in n:
                flags["replay_protection"] = bool(ext.value)
            elif "idempot" in n:
                flags["idempotency"] = bool(ext.value)
            elif "retry" in n:
                flags["retry"] = bool(ext.value)
        out.append(
            WebhookModel(
                name=wh.name,
                direction="outbound",
                signature_verification=flags["signature_verification"],
                replay_protection=flags["replay_protection"],
                idempotency=flags["idempotency"],
                retry=flags["retry"],
                evidence=_ev(
                    EvidenceKind.STATIC, wh.location.path,
                    f"webhook {wh.name}", wh.location.line,
                ),
            )
        )
    return tuple(sorted(out, key=lambda w: w.name))


def contract_classifications(
    model: OpenApiProjectModel,
) -> tuple[DataClassification, ...]:
    """§124 - ONLY explicit `x-` metadata, never name inference."""
    out: list[DataClassification] = []
    for ext in model.extensions:
        n = ext.name.lower()
        if n not in _SENSITIVE_EXT:
            continue
        # property-level markers are recorded by the schema walk with a
        # canonical `Schema.prop` subject; skip the raw pointer form here
        if "/properties/" in (ext.owner_pointer or ""):
            continue
        cat = _category(ext.value, n)
        if cat is None:
            continue
        out.append(
            DataClassification(
                subject=ext.owner_pointer or ext.pointer,
                category=cat,
                evidence=_ev(
                    EvidenceKind.STATIC, ext.location.path,
                    f"classification {ext.name}", ext.location.line,
                ),
            )
        )
    # property-level: schema content walking for x-classified properties
    for schema in model.schemas:
        _walk_schema_props(schema.content, schema, out)
    return tuple(sorted(set(out), key=lambda c: c.subject))


_CATEGORIES = {c.value: c for c in DataCategory}


def _category(value: Any, ext_name: str) -> DataCategory | None:
    if ext_name == "x-pii" and value:
        return DataCategory.PII
    if isinstance(value, str):
        return _CATEGORIES.get(value.lower())
    if isinstance(value, dict):
        return _CATEGORIES.get(str(value.get("category", "")).lower())
    if value is True:
        return DataCategory.INTERNAL
    return None


def _walk_schema_props(node: Any, schema: Any,
                       out: list[DataClassification],
                       depth: int = 0) -> None:
    if depth > 12 or not isinstance(node, dict):
        return
    props = node.get("properties")
    if isinstance(props, dict):
        for name, body in props.items():
            if not isinstance(body, dict):
                continue
            for k, v in body.items():
                if str(k).lower() in _SENSITIVE_EXT:
                    cat = _category(v, str(k).lower())
                    if cat:
                        out.append(
                            DataClassification(
                                subject=f"{schema.name}.{name}",
                                category=cat,
                                evidence=_ev(
                                    EvidenceKind.STATIC,
                                    schema.location.path,
                                    f"property {schema.name}.{name} "
                                    f"classified {cat.value}",
                                    schema.location.line,
                                ),
                            )
                        )
            _walk_schema_props(body, schema, out, depth + 1)


def contract_pagination(
    model: OpenApiProjectModel,
) -> tuple[PaginationModel, ...]:
    """§118 pagination evidence per operation."""
    params_by_ptr = {p.pointer: p for p in model.parameters}
    out: list[PaginationModel] = []
    for op in model.operations:
        names = {
            (params_by_ptr[ptr].name or "").lower()
            for ptr in op.parameter_pointers
            if ptr in params_by_ptr
        }
        kind = PaginationKind.NONE
        limit_param: str | None = None
        bounded: bool | None = None
        if names & _TOKEN_PARAMS:
            kind, bounded = PaginationKind.TOKEN, True
        elif names & _CURSOR_PARAMS:
            kind, bounded = PaginationKind.CURSOR, True
        elif names & _OFFSET_PARAMS:
            kind, bounded = PaginationKind.OFFSET, bool(names & _LIMIT_PARAMS)
        limit = names & _LIMIT_PARAMS
        if limit:
            limit_param = sorted(limit)[0]
            bounded = True
            if kind is PaginationKind.NONE:
                kind = PaginationKind.OFFSET
        out.append(
            PaginationModel(
                operation=op.identity,
                kind=kind,
                bounded=bounded,
                limit_param=limit_param,
                evidence=_ev(
                    EvidenceKind.STATIC, op.location.path,
                    f"pagination {kind.value} on {op.identity}",
                    op.location.line,
                ),
            )
        )
    return tuple(sorted(out, key=lambda p: p.operation))


# ---------- implementation plane ----------


def impl_authz(routes: RouteScan) -> tuple[AuthorizationPolicy, ...]:
    """`Security(...)` names are auth evidence, never policy."""
    out = [
        AuthorizationPolicy(
            operation=f"{r.method.upper()} {r.path}",
            roles=(),
            scopes=(),
            claims=(),
            ownership_check=None,
            plane="implementation",
            evidence=_ev(
                EvidenceKind.STATIC, r.source_location.path,
                f"impl auth deps {sorted(r.auth)} on {r.path}",
                r.source_location.line,
            ),
        )
        for r in routes.routes
        if r.auth
    ]
    return tuple(sorted(out, key=lambda p: p.operation))


def impl_schemes(routes: RouteScan) -> tuple[AuthenticationScheme, ...]:
    names = sorted({n for r in routes.routes for n in r.auth})
    return tuple(
        AuthenticationScheme(
            name=n,
            type=AuthSchemeType.CUSTOM,
            plane="implementation",
            evidence=_ev(
                EvidenceKind.STATIC, "(routes)",
                f"impl security dependency {n}",
            ),
        )
        for n in names
    )


# ---------- config plane ----------


def _walk_config(node: Any, path: str, trail: tuple[str, ...],
                 text: str, out: dict[str, list[Any]]) -> None:
    if not isinstance(node, dict):
        return
    low = {str(k).lower(): k for k in node}

    def get(*names: str) -> Any:
        for n in names:
            if n.lower() in low:
                return node[low[n.lower()]]
        return None

    for ck in _CORS_KEYS:
        cors = node.get(ck)
        if cors is None:
            continue
        body = cors if isinstance(cors, dict) else node
        blow = {str(k).lower(): k for k in body}
        origins = _as_str_list(
            body.get(blow.get("allowed_origins", "allowed_origins"))
            or body.get(blow.get("allow_origins", "allow_origins"))
            or body.get(blow.get("alloworigins", "alloworigins"))
        )
        creds = body.get(blow.get("allow_credentials", "allow_credentials"))
        if creds is None:
            creds = body.get(blow.get("allowcredentials", "allowcredentials"))
        methods = _as_str_list(
            body.get(blow.get("allowed_methods", "allowed_methods"))
            or body.get(blow.get("allowmethods", "allowmethods"))
        )
        headers = _as_str_list(
            body.get(blow.get("allowed_headers", "allowed_headers"))
            or body.get(blow.get("allowheaders", "allowheaders"))
        )
        scope = _nearest(body, trail) or _nearest(node, trail) \
            or Path(path).stem
        out["cors"].append(
            CorsPolicy(
                scope=str(scope),
                allowed_origins=origins,
                credentials=bool(creds) if creds is not None else None,
                methods=methods,
                headers=headers,
                wildcard="*" in origins,
                location=SourceLocation(path=path, line=_line_of(text, ck)),
                evidence=_ev(EvidenceKind.CONFIG, path,
                             f"CORS at {scope}",
                             _line_of(text, ck)),
            )
        )
        break

    for rk in _RL_KEYS:
        rl = node.get(rk)
        if rl is None:
            continue
        body = rl if isinstance(rl, dict) else node
        blow = {str(k).lower(): k for k in body}
        scope = _nearest(body, trail) or _nearest(node, trail) \
            or Path(path).stem
        out["rl"].append(
            RateLimitPolicy(
                scope=str(scope),
                limit=_num(body.get(blow.get("limit", "limit"))
                           or body.get(blow.get("requests", "requests"))
                           or body.get(blow.get("rps", "rps"))
                           or body.get(blow.get("rate", "rate"))),
                window=(
                    str(body[blow["window"]]) if "window" in blow
                    else str(body[blow["per"]]) if "per" in blow
                    else None
                ),
                burst=_num(body.get(blow.get("burst", "burst"))),
                key=(str(body[blow["key"]]) if "key" in blow else None),
                location=SourceLocation(path=path, line=_line_of(text, rk)),
                evidence=_ev(EvidenceKind.CONFIG, path,
                             f"rate limit at {scope}",
                             _line_of(text, rk)),
            )
        )
        break

    for tk in _TLS_KEYS:
        if node.get(tk) is None:
            continue
        kind = "mtls" if "mtls" in tk.lower() or "client_cert" in tk.lower() \
            else "tls"
        tbody = node[tk] if isinstance(node[tk], dict) else node
        out["tls"].append(
            TlsEvidence(
                scope=str(_nearest(tbody, trail) or Path(path).stem),
                kind=kind,
                detail=tk,
                evidence=_ev(EvidenceKind.CONFIG, path,
                             f"{kind} config", _line_of(text, tk)),
            )
        )

    for gk in _GW_AUTHZ_KEYS:
        gw = node.get(gk)
        if gw is None:
            continue
        body = gw if isinstance(gw, dict) else {}
        blow = {str(k).lower(): k for k in body}
        gw_scope = _nearest(gw, trail) if isinstance(gw, dict) else None
        out["gw"].append(
            AuthorizationPolicy(
                operation=str(gw_scope or _nearest(node, trail)
                              or Path(path).stem),
                roles=_as_str_list(body.get(blow.get("roles", "roles"))),
                scopes=_as_str_list(body.get(blow.get("scopes", "scopes"))),
                plane="gateway",
                evidence=_ev(EvidenceKind.CONFIG, path,
                             f"gateway authz {gk}", _line_of(text, gk)),
            )
        )
        break

    for wk in _WEBHOOK_KEYS:
        wh = node.get(wk)
        if wh is None:
            continue
        items = wh if isinstance(wh, (list, dict)) else []
        if isinstance(items, dict):
            items = [{"name": k, **v} if isinstance(v, dict) else {"name": k}
                     for k, v in items.items()]
        for item in items:
            if not isinstance(item, dict):
                continue
            ilow = {str(k).lower(): k for k in item}

            def iget(*ns: str, _i: dict[str, Any] = item,
                     _l: dict[str, str] = ilow) -> Any:
                for n in ns:
                    if n.lower() in _l:
                        return _i[_l[n.lower()]]
                return None

            name = str(iget("name", "path", "url", "event")
                       or _nearest(node, trail) or "webhook")
            out["webhooks"].append(
                WebhookModel(
                    name=name,
                    direction=str(iget("direction") or "unknown"),
                    signature_verification=(
                        bool(iget("signature", "signature_verification",
                                  "x_signature", "secret"))
                        if iget("signature", "signature_verification",
                                "x_signature", "secret") is not None
                        else None
                    ),
                    replay_protection=(
                        bool(iget("replay_protection", "timestamp"))
                        if iget("replay_protection", "timestamp") is not None
                        else None
                    ),
                    idempotency=(
                        bool(iget("idempotency", "idempotent"))
                        if iget("idempotency", "idempotent") is not None
                        else None
                    ),
                    retry=(
                        bool(iget("retry", "retries"))
                        if iget("retry", "retries") is not None
                        else None
                    ),
                    evidence=_ev(EvidenceKind.CONFIG, path,
                                 f"webhook {name}", _line_of(text, wk)),
                )
            )
        break

    for ek in _EXT_API_KEYS:
        ext = node.get(ek)
        if ext is None:
            continue
        items = ext if isinstance(ext, list) else [ext]
        for item in items:
            if not isinstance(item, dict):
                continue
            ilow = {str(k).lower(): k for k in item}
            host = item.get(ilow.get("host", "host")) or \
                item.get(ilow.get("url", "url")) or \
                item.get(ilow.get("base_url", "base_url"))
            if not host:
                continue
            timeout = item.get(ilow.get("timeout", "timeout"))
            out["ext"].append(
                ExternalApi(
                    host=str(host),
                    operations=_as_str_list(
                        item.get(ilow.get("operations", "operations"))),
                    timeout_ms=_num(timeout),
                    has_retry=("retry" in ilow or "retries" in ilow),
                    has_auth=("auth" in ilow or "api_key" in ilow
                              or "credentials" in ilow),
                    owner=(str(item[ilow["owner"]]) if "owner" in ilow
                           else None),
                    criticality=(str(item[ilow["criticality"]])
                                 if "criticality" in ilow else None),
                    evidence=_ev(EvidenceKind.CONFIG, path,
                                 f"external api {host}", _line_of(text, ek)),
                )
            )
        break

    for fk in _FLOW_KEYS:
        fl = node.get(fk)
        if fl is None:
            continue
        items = fl if isinstance(fl, list) else [fl]
        for item in items:
            if not isinstance(item, dict):
                continue
            ilow = {str(k).lower(): k for k in item}
            flow_name = item.get(ilow.get("name", "name"))
            if not flow_name:
                continue
            out["flows"].append(
                SensitiveBusinessFlow(
                    name=str(flow_name),
                    description=(str(item[ilow["description"]])
                                 if "description" in ilow else None),
                    protections=_as_str_list(
                        item.get(ilow.get("protections", "protections"))),
                    evidence=_ev(EvidenceKind.CONFIG, path,
                                 f"business flow {flow_name}",
                                 _line_of(text, fk)),
                )
            )
        break

    for key, val in node.items():
        ktrail = (*trail, str(key))
        if isinstance(val, dict):
            _walk_config(val, path, ktrail, text, out)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _walk_config(item, path, ktrail, text, out)


def _scan_python_cors(context: ProjectContext, files: list[str],
                      out: dict[str, list[Any]]) -> None:
    """`CORSMiddleware(allow_origins=...)` call-site evidence."""
    for path in sorted(files):
        if not path.endswith(".py"):
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        if not _PY_CORS_RE.search(text):
            continue
        m = _PY_ALLOW_ORIGINS.search(text)
        raw = m.group(1) if m else ""
        raw = raw.strip().strip("[]")
        origins = tuple(
            s.strip().strip("'\"") for s in raw.split(",") if s.strip()
        )
        creds = _PY_ALLOW_CREDS.search(text)
        out["cors"].append(
            CorsPolicy(
                scope=Path(path).stem,
                allowed_origins=origins,
                credentials=(creds.group(1) == "True") if creds else None,
                wildcard="*" in origins or (m is not None and m.group(1) == "*"),
                location=SourceLocation(
                    path=path, line=_line_of(text, "CORSMiddleware")),
                evidence=_ev(EvidenceKind.STATIC, path,
                             "CORSMiddleware call site",
                             _line_of(text, "CORSMiddleware")),
            )
        )


# ---------- auth drift (§53) ----------


def normalize_route_path(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"


def _match_route(op: OpenApiOperation, routes: tuple[RouteModel, ...]) -> RouteModel | None:
    norm = normalize_route_path(op.path)
    for r in routes:
        if r.method.lower() == op.method.lower() and \
                normalize_route_path(r.path) == norm:
            return r
    if op.operation_id:
        for r in routes:
            if r.handler.rsplit(".", 1)[-1] == op.operation_id:
                return r
    return None


def _op_planes(
    model: OpenApiProjectModel,
    routes: RouteScan | None,
    gateway_policies: tuple[AuthorizationPolicy, ...],
) -> tuple[tuple[OpenApiOperation, bool | None, bool | None,
                 bool | None, tuple[str, ...]], ...]:
    """Per-op (contract_secured, impl_secured, gateway_secured, schemes).

    Shared plane resolution for `auth_drift` + `auth_chain` — scheme
    names come from resolved requirements (op-level first, then global),
    never from name guessing.
    """
    impl_routes = routes.routes if routes else ()
    global_reqs = tuple(
        r for r in model.security_requirements if r.owner_pointer == "")
    out = []
    for op in model.operations:
        req, _ = op_requires_auth(model, op)
        route = _match_route(op, impl_routes)
        impl_sec: bool | None = (
            bool(route.auth) if route is not None
            else (False if impl_routes else None)
        )
        norm = normalize_route_path(op.path)
        gw_sec: bool | None = (
            any(norm in normalize_route_path(p.operation) or p.operation == "*"
                or normalize_route_path(p.operation) in norm
                for p in gateway_policies)
            if gateway_policies else None
        )
        if op.has_security:
            effective = tuple(
                r for r in model.security_requirements
                if r.owner_pointer == op.pointer)
        else:
            effective = global_reqs
        schemes = tuple(sorted(
            {s.name for r in effective for s in r.schemes}))
        out.append((op, req, impl_sec, gw_sec, schemes))
    return tuple(out)


def auth_drift(
    model: OpenApiProjectModel,
    routes: RouteScan | None,
    gateway_policies: tuple[AuthorizationPolicy, ...],
) -> tuple[AuthDrift, ...]:
    """§53 compare contract vs impl vs gateway auth evidence per op."""
    if routes is None and not gateway_policies:
        return ()
    out: list[AuthDrift] = []
    for op, req, impl_sec, gw_sec, _schemes in _op_planes(
            model, routes, gateway_policies):
        planes = [req, impl_sec, gw_sec]
        known = [p for p in planes if p is not None]
        if len(known) < 2 or all(p == known[0] for p in known):
            continue
        detail = (
            f"contract_secured={req} impl_secured={impl_sec} "
            f"gateway_secured={gw_sec}"
        )
        out.append(
            AuthDrift(
                operation=op.identity,
                contract_secured=req,
                impl_secured=impl_sec,
                gateway_secured=gw_sec,
                detail=detail,
                evidence=_ev(
                    EvidenceKind.STATIC, op.location.path,
                    f"auth drift on {op.identity}", op.location.line,
                ),
            )
        )
    return tuple(sorted(out, key=lambda d: d.operation))


def auth_chain(
    model: OpenApiProjectModel,
    routes: RouteScan | None,
    gateway_policies: tuple[AuthorizationPolicy, ...],
) -> tuple[AuthChainLink, ...]:
    """§51-53 chain records: declared scheme -> enforcement plane.

    A record exists for every op with at least one evidenced plane —
    complete when a declared scheme lands on implementation or gateway
    enforcement; a break when declared auth finds no enforcement, or
    enforcement exists without a contract declaration.
    """
    links: list[AuthChainLink] = []
    for op, req, impl_sec, gw_sec, schemes in _op_planes(
            model, routes, gateway_policies):
        declared = req is True
        enforced = impl_sec is True or gw_sec is True
        if req is None and impl_sec is None and gw_sec is None:
            continue
        point = ("implementation" if impl_sec else
                 "gateway" if gw_sec else
                 "contract-only" if declared else "none")
        if declared and enforced:
            complete: bool | None = True
        elif declared != enforced:
            complete = False
        else:
            complete = None
        links.append(AuthChainLink(
            operation=op.identity, scope=op.identity,
            scheme_declared=", ".join(schemes) if schemes else None,
            enforcement_point=point, chain_complete=complete,
            evidence_refs=_ev(
                EvidenceKind.STATIC, op.location.path,
                f"auth chain on {op.identity}: declared="
                f"{schemes or None} enforced={point}",
                op.location.line)))
    return tuple(sorted(links, key=lambda x: (x.operation, x.scope)))


# ---------- entry point ----------


def load_security_model(
    context: ProjectContext,
    files: list[str],
    openapi: OpenApiProjectModel | None = None,
    routes: RouteScan | None = None,
) -> ApiSecurityModel:
    """Aggregate passive security evidence into `ApiSecurityModel`."""
    out: dict[str, list[Any]] = {
        "cors": [], "rl": [], "tls": [], "gw": [], "webhooks": [],
        "ext": [], "flows": [],
    }
    for path in sorted(files):
        if Path(path).suffix.lower() not in _CONFIG_SUFFIXES:
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            _walk_config(doc, path, (), text, out)

    _scan_python_cors(context, files, out)

    auth_schemes: list[AuthenticationScheme] = []
    authz: list[AuthorizationPolicy] = []
    webhooks: list[WebhookModel] = list(out["webhooks"])
    classifications: list[DataClassification] = []
    pagination: list[PaginationModel] = []
    drift: tuple[AuthDrift, ...] = ()
    chain: tuple[AuthChainLink, ...] = ()

    if openapi is not None:
        auth_schemes.extend(contract_schemes(openapi))
        authz.extend(contract_authz(openapi))
        webhooks.extend(contract_webhooks(openapi))
        classifications.extend(contract_classifications(openapi))
        pagination.extend(contract_pagination(openapi))
    if routes is not None:
        auth_schemes.extend(impl_schemes(routes))
        authz.extend(impl_authz(routes))

    gw = tuple(sorted(out["gw"], key=lambda p: p.operation))
    authz.extend(gw)
    if openapi is not None:
        drift = auth_drift(openapi, routes, gw)
        chain = auth_chain(openapi, routes, gw)

    cors = tuple(sorted(out["cors"], key=lambda c: (c.scope, c.location.path
                                                  if c.location else "")))
    return ApiSecurityModel(
        auth_schemes=tuple(sorted(auth_schemes,
                                  key=lambda s: (s.plane, s.name))),
        authorization=tuple(sorted(authz,
                                   key=lambda p: (p.operation, p.plane))),
        auth_drift=drift,
        auth_chain=chain,
        rate_limits=tuple(sorted(out["rl"], key=lambda r: r.scope)),
        cors=cors,
        tls=tuple(sorted(out["tls"], key=lambda t: t.scope)),
        webhooks=tuple(sorted(webhooks, key=lambda w: w.name)),
        pagination=tuple(sorted(pagination, key=lambda p: p.operation)),
        classifications=tuple(sorted(classifications,
                                     key=lambda c: c.subject)),
        external_apis=tuple(sorted(out["ext"], key=lambda e: e.host)),
        business_flows=tuple(sorted(out["flows"], key=lambda f: f.name)),
        evidence=(
            Evidence(
                kind=EvidenceKind.CONFIG,
                source="(project)",
                summary=f"{len(auth_schemes)} auth schemes, "
                f"{len(authz)} authz policies, {len(cors)} cors, "
                f"{len(out['rl'])} rate limits",
            ),
        ),
        unknowns=(
            UnknownFact(
                subject="runtime security signals",
                missing="live traffic/WAF evidence",
                resolution="static evidence only - passive by design (§1)",
            ),
        ),
    )
