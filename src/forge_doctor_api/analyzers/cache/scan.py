"""§151-153 cache evidence extraction.

Sources: OpenAPI response `Cache-Control` headers → client/cdn layer
policies; config keys under `cache:`/`cdn:`/`ttl:` → service/gateway
policies. `InvalidationRisk` fires only when a declared policy and a
mutation (write method on the same path) both have evidence.
"""

from __future__ import annotations

import yaml

from forge_doctor_api.analyzers.cache.model import (
    ApiCacheModel,
    CacheLayer,
    CachePolicy,
    InvalidationRisk,
)
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Severity,
    SourceLocation,
    UnknownFact,
)

_WRITE_METHODS = {"post", "put", "patch", "delete"}
_CONFIG_SUFFIXES = {".yaml", ".yml", ".json"}
_CACHE_KEYS = ("cache", "caching", "cdn", "ttl")


def _header_policy(subject: str, loc: SourceLocation) -> CachePolicy:
    """Cache-Control *declared* on a response → client-layer policy.

    The OpenAPI model retains header names, not values — so `ttl` and
    `stale_policy` stay `None` here rather than being guessed.
    """
    return CachePolicy(
        subject=subject, layer=CacheLayer.CLIENT, location=loc)


def _config_policies(
    context: ProjectContext, files: list[str]
) -> tuple[list[CachePolicy], list[UnknownFact]]:
    policies: list[CachePolicy] = []
    unknowns: list[UnknownFact] = []
    for rel in sorted(files):
        if not rel.endswith(tuple(_CONFIG_SUFFIXES)):
            continue
        try:
            raw = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            continue
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError:
            if any(k in raw for k in _CACHE_KEYS):
                unknowns.append(UnknownFact(
                    subject=rel,
                    missing="parseable cache config",
                    resolution="file has cache markers but invalid YAML"))
            continue
        if not isinstance(doc, dict):
            continue
        for key in _CACHE_KEYS:
            block = doc.get(key)
            if not isinstance(block, dict):
                continue
            for scope, body in block.items():
                if not isinstance(body, dict):
                    policies.append(CachePolicy(
                        subject=str(scope), layer=CacheLayer.UNKNOWN,
                        ttl=str(body) if body is not None else None,
                        location=SourceLocation(path=rel)))
                    continue
                layer = CacheLayer.UNKNOWN
                declared_layer = str(body.get("layer") or "").lower()
                try:
                    layer = CacheLayer(declared_layer)
                except ValueError:
                    if key == "cdn":
                        layer = CacheLayer.CDN
                    elif key in ("cache", "caching"):
                        layer = CacheLayer.SERVICE
                vary_raw = body.get("vary") or body.get("vary_headers")
                vary = (
                    tuple(str(v) for v in vary_raw)
                    if isinstance(vary_raw, (list, tuple))
                    else (tuple(s.strip() for s in str(vary_raw).split(",")
                                if s.strip()) if vary_raw else ())
                )
                cscope = body.get("scope") or body.get("visibility")
                if cscope is None:
                    if body.get("private") is True:
                        cscope = "private"
                    elif body.get("public") is True:
                        cscope = "public"
                stale = (
                    str(body["stale_policy"]) if body.get("stale_policy")
                    else None
                )
                sie = (
                    body.get("stale_if_error", body.get("staleIfError",
                             body.get("stale-if-error")))
                )
                if sie is not None:
                    stale = f"stale-if-error:{sie}" if stale is None \
                        else f"{stale};stale-if-error:{sie}"
                policies.append(CachePolicy(
                    subject=str(scope),
                    layer=layer,
                    ttl=(str(body["ttl"]) if body.get("ttl") is not None
                         else None),
                    key=(str(body["key"]) if body.get("key") else None),
                    invalidation=(str(body["invalidation"])
                                  if body.get("invalidation") else None),
                    stale_policy=stale,
                    vary=vary,
                    scope=(str(cscope) if cscope is not None else None),
                    location=SourceLocation(path=rel)))
    return policies, unknowns


def _openapi_policies(model: OpenApiProjectModel) -> list[CachePolicy]:
    policies: list[CachePolicy] = []
    for op in model.operations:
        for resp in model.responses:
            if resp.pointer not in op.response_pointers:
                continue
            if any(h.lower() == "cache-control" for h in resp.header_names):
                policies.append(_header_policy(op.identity, resp.location))
    return policies


def load_cache_model(
    context: ProjectContext,
    files: list[str],
    *,
    openapi: OpenApiProjectModel | None = None,
) -> ApiCacheModel:
    """Declared cache policies + §153 invalidation-risk candidates."""
    policies, unknowns = _config_policies(context, files)
    if openapi is not None:
        header_policies = _openapi_policies(openapi)
        policies.extend(header_policies)
        # A declared Cache-Control header name is presence evidence only
        # - ttl/key/invalidation/stale_policy are contract-invisible, so
        # each header-only policy carries an explicit unknown (§152).
        seen: set[str] = set()
        for pol in header_policies:
            if pol.subject in seen:
                continue
            seen.add(pol.subject)
            unknowns.append(UnknownFact(
                subject=pol.subject,
                missing="declared cache fields (ttl, key, invalidation, "
                "stale_policy)",
                resolution="Cache-Control header declared on the "
                "response, but header names carry no values - declare "
                "the policy fields in config or x- extensions to make "
                "cache semantics checkable"))

    risks: list[InvalidationRisk] = []
    if openapi is not None:
        write_subjects = {
            op.path for op in openapi.operations
            if op.method.lower() in _WRITE_METHODS}
        for pol in policies:
            for path in write_subjects:
                if pol.subject.endswith(path) or path in pol.subject:
                    risks.append(InvalidationRisk(
                        subject=pol.subject,
                        detail=(
                            f"cache policy on {pol.subject} coexists with "
                            f"mutating methods on {path}"),
                        severity=Severity.MEDIUM,
                        confidence=Confidence.LOW,
                        evidence=(Evidence(
                            kind=EvidenceKind.CONFIG,
                            source=pol.location.path,
                            line=pol.location.line,
                            summary=f"{pol.layer} cache policy"),)))
    return ApiCacheModel(
        policies=tuple(sorted(
            policies, key=lambda p: (p.subject, p.layer.value))),
        risks=tuple(sorted(risks, key=lambda r: r.subject)),
        unknowns=tuple(sorted(
            {u.subject: u for u in unknowns}.values(),
            key=lambda u: (u.subject, u.missing))))
