"""§77-§83 migration analysis over existing domain models.

All comparisons are dimension-driven: every assessment reports the full
dimension set with per-dimension evidence, preserved/lost semantics, and
explicit unknowns. Rollup is worst-dimension-wins so a clean verdict can
never hide an unassessed dimension.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from forge_doctor_api.analyzers.asyncapi.model import AsyncApiProjectModel
from forge_doctor_api.analyzers.openapi.knowledge import version_family
from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.analyzers.openapi.shape import schema_shape
from forge_doctor_api.checks.compat.engine import ContractDiff, diff_models
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.knowledge.loader import domain_packs, load_pack
from forge_doctor_api.migrate.model import (
    ApiMigrationIntelligence,
    DecisionBrief,
    DecisionQuestion,
    DimensionResult,
    MigrationAssessment,
    MigrationClass,
    MigrationKind,
    SdkImpact,
    rollup,
)
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    IdempotencyVerdict,
)
from forge_doctor_api.security.model import ApiSecurityModel


def _pack_fields(domain: str, name: str, entry_id: str) -> dict[str, Any]:
    pack = load_pack(domain, name)
    entry = pack.entry(entry_id)
    return entry.fields if entry is not None else {}


_IDEMPOTENT_METHODS = frozenset(
    str(m).lower()
    for m in _pack_fields("http", "semantics.yaml", "methods").get(
        "idempotent", ())
)
_STATUS_MAP: dict[str, str] = {
    str(k): str(v)
    for k, v in (
        _pack_fields("grpc", "behaviors.yaml", "http-to-grpc-status").get(
            "mapping", {}) or {}
    ).items()
}
_CANON_GW: dict[str, dict[str, str]] = {
    str(k): {str(ak): str(av) for ak, av in dict(v).items()}
    for k, v in (
        _pack_fields("gateways", "capability-map.yaml", "canonical").get(
            "map", {}) or {}
    ).items()
    if isinstance(v, dict)
}
_OAS_PACK = load_pack("openapi", "versions.yaml")


def _ev(location: SourceLocation | None, summary: str,
        kind: EvidenceKind = EvidenceKind.STATIC) -> tuple[Evidence, ...]:
    if location is None:
        return ()
    return (Evidence(kind=kind, source=location.path, summary=summary,
                     line=location.line),)


def _dim(dimension: str, cls: MigrationClass, detail: str,
         evidence: tuple[Evidence, ...] = (),
         preserved: tuple[str, ...] = (), lost: tuple[str, ...] = (),
         unknowns: tuple[UnknownFact, ...] = ()) -> DimensionResult:
    return DimensionResult(
        dimension=dimension, classification=cls, detail=detail,
        evidence=evidence, preserved=preserved, lost=lost, unknowns=unknowns,
    )


def _unk(subject: str, missing: str, resolution: str) -> UnknownFact:
    return UnknownFact(subject=subject, missing=missing, resolution=resolution)


def _assessment(subject: str, kind: MigrationKind,
                dims: list[DimensionResult]) -> MigrationAssessment:
    return MigrationAssessment(
        subject=subject,
        kind=kind,
        classification=rollup([d.classification for d in dims]),
        dimensions=tuple(dims),
        preserved=tuple(p for d in dims for p in d.preserved),
        lost=tuple(x for d in dims for x in d.lost),
        unknowns=tuple(u for d in dims for u in d.unknowns),
    )


# ---------------------------------------------------------------- rest->grpc

_COMPLEX_SHAPES = ("allOf", "anyOf", "oneOf", "not", "ap:free",
                   "pattern-props", "schema:?")
_COMPOSED_SHAPES = ("type:object", "props(", "items", "ref:")
_ERROR_CODES = {"4", "5"}


def _shape_class(shapes: tuple[str, ...]) -> tuple[MigrationClass, str]:
    if not shapes:
        return MigrationClass.UNKNOWN, "no schema declared"
    tokens = set(shapes)
    if any(s in tokens or s.rstrip(":") in tokens for s in _COMPLEX_SHAPES) or \
            any(any(t in s for t in ("anyOf", "oneOf", "allOf", "ap:free",
                                     "pattern-props")) for s in shapes):
        return (
            MigrationClass.APPROXIMATE,
            "polymorphic/free-form shapes need oneof/map redesign in proto",
        )
    if any(any(t in s for t in ("type:object", "props(", "items",
                              "type:array", "ref:")) for s in shapes):
        return (
            MigrationClass.APPROXIMATE,
            "nested/array shapes map to proto messages with field-type loss",
        )
    return MigrationClass.DIRECT, "scalar shapes map to proto scalar fields"


def _rest_to_grpc_dims(
    op: OpenApiOperation,
    openapi: OpenApiProjectModel,
    reliability: ApiReliabilityModel | None,
) -> list[DimensionResult]:
    params = [p for p in openapi.parameters
              if p.pointer in op.parameter_pointers]
    body = next((b for b in openapi.request_bodies
                 if b.pointer == op.request_body_pointer), None)
    responses = [r for r in openapi.responses
                 if r.pointer in op.response_pointers]
    dims: list[DimensionResult] = []

    # request/response
    req_shapes: tuple[str, ...] = (
        *(body.schema_shapes if body else ()),
        *(schema_shape(p.schema) for p in params if p.schema is not None),
    )
    resp_shapes = tuple(s for r in responses for s in r.schema_shapes)
    req_cls, req_detail = (
        (MigrationClass.DIRECT, "no request body or parameters declared")
        if not req_shapes
        else _shape_class(req_shapes)
    )
    resp_cls, resp_detail = (
        (MigrationClass.UNKNOWN, "no response schemas declared")
        if not responses
        else _shape_class(resp_shapes)
    )
    ev = tuple(e for loc in (
        [b.location for b in [body] if b is not None]
        + [r.location for r in responses]
        + [p.location for p in params])
        for e in _ev(loc, "declared shape"))
    dims.append(_dim(
        "request/response", rollup([req_cls, resp_cls]),
        f"request: {req_detail}; response: {resp_detail}",
        evidence=ev,
        preserved=("scalar fields", "declared parameter names"),
        lost=tuple(x for x in (
            "json number/float precision" if resp_cls is not MigrationClass.DIRECT
            or req_cls is not MigrationClass.DIRECT else None,
        ) if x),
        unknowns=() if req_cls is not MigrationClass.UNKNOWN
        and resp_cls is not MigrationClass.UNKNOWN
        else (_unk(op.identity, "declared schema detail",
                   "declare request/response schemas"),),
    ))

    # status semantics
    if not responses:
        dims.append(_dim(
            "status semantics", MigrationClass.UNKNOWN,
            "no responses declared",
            unknowns=(_unk(op.identity, "response status codes",
                           "declare responses for the operation"),),
        ))
    else:
        unmapped: list[str] = []
        for r in responses:
            for code in (r.status or "default",):
                if code in _STATUS_MAP or code == "default":
                    continue
                if code.isdigit() and code[0] in "12345":
                    unmapped.append(code)
        dims.append(_dim(
            "status semantics",
            MigrationClass.APPROXIMATE if unmapped else MigrationClass.DIRECT,
            "all statuses map to gRPC codes" if not unmapped else
            f"statuses without canonical gRPC code: {sorted(set(unmapped))}",
            evidence=tuple(
                e for r in responses for e in _ev(r.location, "status")),
            preserved=("2xx -> OK", "4xx/5xx -> canonical gRPC codes"),
            lost=tuple(unmapped),
        ))

    # streaming
    stream_ct = {"text/event-stream", "application/x-ndjson",
                 "application/stream+json"}
    streamed = any(
        ct in stream_ct
        for r in responses for ct in r.content_types
    ) or any(ct in stream_ct for ct in (body.content_types if body else ()))
    dims.append(_dim(
        "streaming",
        MigrationClass.APPROXIMATE if streamed else MigrationClass.DIRECT,
        "streaming payload -> server/bidi streaming method"
        if streamed else "unary request/response",
        evidence=tuple(
            e for r in responses for e in _ev(r.location, "content type")),
        lost=("chunked/http1 framing",) if streamed else (),
    ))

    # metadata/headers
    header_params = [p for p in params if p.location_in == "header"]
    resp_headers = sorted({h for r in responses for h in r.header_names})
    has_headers = bool(header_params or resp_headers)
    dims.append(_dim(
        "metadata/headers",
        MigrationClass.APPROXIMATE if has_headers else MigrationClass.DIRECT,
        "headers carry as gRPC metadata; hop-by-hop headers are lost"
        if has_headers else "no header surface declared",
        evidence=tuple(
            e for p in header_params for e in _ev(p.location, "header param")),
        preserved=tuple(h for h in resp_headers),
        lost=("hop-by-hop headers",) if has_headers else (),
    ))

    # error model
    error_resps = [
        r for r in responses
        if r.status and r.status.isdigit() and r.status[0] in _ERROR_CODES
    ]
    problem = any("problem" in ct for r in error_resps
                  for ct in r.content_types)
    dims.append(_dim(
        "error model",
        MigrationClass.DIRECT if not error_resps else MigrationClass.APPROXIMATE,
        "no error responses declared" if not error_resps else
        ("RFC7807 problem bodies map to google.rpc.Status details"
         if problem else
         "error bodies need google.rpc.Status detail mapping"),
        evidence=tuple(
            e for r in error_resps for e in _ev(r.location, "error status")),
        preserved=("http problem+json -> rich error details",)
        if problem else (),
        lost=tuple(f"error body for {r.status}" for r in error_resps
                   if not problem),
    ))

    # timeouts
    timeouts = reliability.timeouts if reliability else ()
    if timeouts:
        dims.append(_dim(
            "timeouts", MigrationClass.DIRECT,
            "declared timeout evidence maps to gRPC deadline",
            evidence=tuple(
                e for t in timeouts for e in t.evidence),
            preserved=tuple(f"timeout at scope {t.scope}" for t in timeouts),
        ))
    else:
        dims.append(_dim(
            "timeouts", MigrationClass.UNKNOWN,
            "no timeout evidence in project",
            unknowns=(_unk(op.identity, "timeout/deadline configuration",
                           "declare timeout config"),),
        ))

    # idempotency
    method = op.method.lower()
    if method in _IDEMPOTENT_METHODS:
        dims.append(_dim(
            "idempotency", MigrationClass.DIRECT,
            f"HTTP {method} is idempotent by RFC9110 semantics",
            preserved=("method-level idempotency",),
        ))
    else:
        idem = [i for i in (reliability.idempotency if reliability else ())
                if i.verdict is IdempotencyVerdict.IDEMPOTENT]
        if idem:
            dims.append(_dim(
                "idempotency", MigrationClass.APPROXIMATE,
                "declared idempotency evidence; gRPC has no method-level "
                "idempotency signal",
                evidence=tuple(
                    e for i in idem for s in i.sources for e in s.evidence),
                preserved=("declared idempotent operation",),
            ))
        else:
            dims.append(_dim(
                "idempotency", MigrationClass.UNKNOWN,
                f"HTTP {method} is not inherently idempotent and no "
                "idempotency evidence is declared",
                unknowns=(_unk(
                    op.identity, "idempotency evidence",
                    "declare idempotency-key / contract metadata"),),
            ))
    return dims


def assess_rest_to_grpc(
    openapi: OpenApiProjectModel,
    reliability: ApiReliabilityModel | None = None,
) -> ApiMigrationIntelligence:
    """§79 REST -> gRPC per-operation dimension comparison."""
    ops = [o for o in openapi.operations
           if o.source is OperationSource.PATH]
    return ApiMigrationIntelligence(
        kind=MigrationKind.REST_TO_GRPC,
        source="rest", target="grpc",
        assessments=tuple(
            _assessment(op.identity, MigrationKind.REST_TO_GRPC,
                        _rest_to_grpc_dims(op, openapi, reliability))
            for op in ops
        ),
        unknowns=() if ops else (_unk(
            "project", "REST operations", "provide an OpenAPI contract"),),
    )


# ------------------------------------------------------------- rest->graphql

def assess_rest_to_graphql(
    openapi: OpenApiProjectModel,
) -> ApiMigrationIntelligence:
    """§80 REST -> GraphQL - REDESIGN_REQUIRED; never endpoint->field maps."""
    ops = [o for o in openapi.operations
           if o.source is OperationSource.PATH]
    assessments = []
    for op in ops:
        dims = [
            _dim(
                "resource model", MigrationClass.REDESIGN_REQUIRED,
                "endpoint-per-resource is not isomorphic to a typed graph "
                "with selection; operation becomes a query/mutation design "
                "decision",
                evidence=_ev(op.location, op.identity),
                lost=("url-addressable resource semantics",),
            ),
            _dim(
                "status semantics", MigrationClass.REDESIGN_REQUIRED,
                "HTTP status codes collapse to 200 + errors[] entries; "
                "error semantics must be redesigned per field",
                lost=("per-status client handling",),
            ),
            _dim(
                "error model", MigrationClass.REDESIGN_REQUIRED,
                "GraphQL errors[] carry path+extensions, not HTTP bodies",
                lost=("http error bodies",),
            ),
            _dim(
                "pagination/filtering", MigrationClass.REDESIGN_REQUIRED,
                "query-string pagination/filtering becomes arguments + "
                "connection types - no automatic mapping",
                lost=("query-parameter contract",),
            ),
        ]
        assessments.append(
            _assessment(op.identity, MigrationKind.REST_TO_GRAPHQL, dims))
    return ApiMigrationIntelligence(
        kind=MigrationKind.REST_TO_GRAPHQL,
        source="rest", target="graphql",
        assessments=tuple(assessments),
        unknowns=() if ops else (_unk(
            "project", "REST operations", "provide an OpenAPI contract"),),
    )


# --------------------------------------------------------------- sync->async

_DLQ_MARKERS = ("dlq", "deadletter", "dead-letter", "dead_letter")
_ORDER_MARKERS = ("ordering", "ordered", "partition", "group", "keyed")
_DELIVERY_MARKERS = ("qos", "at-least", "at-most", "exactly", "delivery")


def _markers_hit(markers: tuple[str, ...], needles: tuple[str, ...]) -> bool:
    low = " ".join(markers).lower()
    return any(n in low for n in needles)


def assess_sync_to_async(
    openapi: OpenApiProjectModel,
    asyncapi: AsyncApiProjectModel | None = None,
    reliability: ApiReliabilityModel | None = None,
) -> ApiMigrationIntelligence:
    """§81 sync -> async per-operation dimension comparison."""
    ops = [o for o in openapi.operations
           if o.source is OperationSource.PATH]
    all_markers: tuple[str, ...] = ()
    if asyncapi is not None:
        all_markers = tuple(
            m
            for coll in (
                asyncapi.channels, asyncapi.operations, asyncapi.messages)
            for el in coll
            for m in (*getattr(el, "markers", ()),
                      *getattr(el, "bindings", ()))
        )
    assessments = []
    for op in ops:
        responses = [r for r in openapi.responses
                     if r.pointer in op.response_pointers]
        has_reply = any(r.has_schema for r in responses)
        dims: list[DimensionResult] = [
            _dim(
                "request-response",
                MigrationClass.REDESIGN_REQUIRED if has_reply
                else MigrationClass.APPROXIMATE,
                "synchronous reply must become correlated message pair"
                if has_reply else "no declared reply body; one-way mapping "
                "is feasible",
                evidence=_ev(op.location, op.identity),
                lost=("synchronous response contract",) if has_reply else (),
            ),
            _dim(
                "delivery semantics",
                MigrationClass.DIRECT if _markers_hit(
                    all_markers, _DELIVERY_MARKERS)
                else MigrationClass.UNKNOWN,
                "delivery semantics declared in async bindings"
                if _markers_hit(all_markers, _DELIVERY_MARKERS)
                else "no delivery-semantics evidence (qos/at-least-once)",
                preserved=("declared delivery semantics",) if _markers_hit(
                    all_markers, _DELIVERY_MARKERS) else (),
                unknowns=() if _markers_hit(all_markers, _DELIVERY_MARKERS)
                else (_unk(op.identity, "delivery semantics declaration",
                           "declare qos/delivery bindings"),),
            ),
            _dim(
                "correlation",
                MigrationClass.DIRECT
                if asyncapi and any(
                    m.correlation_id_location for m in asyncapi.messages)
                else MigrationClass.UNKNOWN,
                "correlation id declared on messages"
                if asyncapi and any(
                    m.correlation_id_location for m in asyncapi.messages)
                else "no correlation-id evidence on messages",
                preserved=("correlation id",) if asyncapi and any(
                    m.correlation_id_location for m in asyncapi.messages)
                else (),
                unknowns=() if asyncapi and any(
                    m.correlation_id_location for m in asyncapi.messages)
                else (_unk(op.identity, "correlation id",
                           "declare correlationId on messages"),),
            ),
            _dim(
                "retry",
                MigrationClass.DIRECT
                if reliability and reliability.retry_policies
                else MigrationClass.UNKNOWN,
                "retry policy evidence present"
                if reliability and reliability.retry_policies
                else "no retry policy evidence",
                evidence=tuple(
                    e for p in (
                        reliability.retry_policies if reliability else ())
                    for e in p.evidence),
                preserved=tuple(
                    f"retry scope {p.scope}"
                    for p in (
                        reliability.retry_policies if reliability else ())),
                unknowns=() if reliability and reliability.retry_policies
                else (_unk(op.identity, "retry policy",
                           "declare retry policy"),),
            ),
            _dim(
                "dlq",
                MigrationClass.DIRECT
                if _markers_hit(all_markers, _DLQ_MARKERS)
                else MigrationClass.UNKNOWN,
                "dead-letter binding declared"
                if _markers_hit(all_markers, _DLQ_MARKERS)
                else "no dead-letter evidence",
                preserved=("dead-letter queue",) if _markers_hit(
                    all_markers, _DLQ_MARKERS) else (),
                unknowns=() if _markers_hit(all_markers, _DLQ_MARKERS)
                else (_unk(op.identity, "dead-letter configuration",
                           "declare dlq/deadLetter bindings"),),
            ),
            _dim(
                "ordering",
                MigrationClass.DIRECT
                if _markers_hit(all_markers, _ORDER_MARKERS)
                else MigrationClass.UNKNOWN,
                "ordering/partition evidence declared"
                if _markers_hit(all_markers, _ORDER_MARKERS)
                else "no ordering evidence",
                preserved=("ordering semantics",) if _markers_hit(
                    all_markers, _ORDER_MARKERS) else (),
                unknowns=() if _markers_hit(all_markers, _ORDER_MARKERS)
                else (_unk(op.identity, "ordering guarantees",
                           "declare partition/ordering bindings"),),
            ),
            _dim(
                "event schema",
                MigrationClass.APPROXIMATE
                if asyncapi and any(
                    m.payload_ref or m.payload_shape
                    for m in asyncapi.messages)
                else MigrationClass.UNKNOWN,
                "message payloads declared in AsyncAPI"
                if asyncapi and any(
                    m.payload_ref or m.payload_shape
                    for m in asyncapi.messages)
                else "no message payload evidence",
                unknowns=() if asyncapi and any(
                    m.payload_ref or m.payload_shape
                    for m in asyncapi.messages)
                else (_unk(op.identity, "event schema",
                           "declare message payloads in AsyncAPI"),),
            ),
        ]
        assessments.append(
            _assessment(op.identity, MigrationKind.SYNC_TO_ASYNC, dims))
    return ApiMigrationIntelligence(
        kind=MigrationKind.SYNC_TO_ASYNC,
        source="sync-rest", target="async",
        assessments=tuple(assessments),
        unknowns=() if ops else (_unk(
            "project", "REST operations", "provide an OpenAPI contract"),),
    )


# ---------------------------------------------------------- gateway->gateway

def _observed_gateway_capabilities(
    security: ApiSecurityModel | None,
) -> tuple[tuple[str, tuple[Evidence, ...]], ...]:
    if security is None:
        return ()
    out: list[tuple[str, tuple[Evidence, ...]]] = []
    if security.rate_limits:
        out.append(("rate-limiting", tuple(
            e for r in security.rate_limits for e in r.evidence)))
    if security.cors:
        out.append(("cors", tuple(
            e for c in security.cors for e in c.evidence)))
    gw_auth = [s for s in security.auth_schemes if s.plane == "gateway"]
    if gw_auth:
        out.append(("auth", tuple(
            e for s in gw_auth for e in s.evidence)))
    mtls = [t for t in security.tls if t.kind == "mtls"]
    if mtls:
        out.append(("mtls", tuple(e for t in mtls for e in t.evidence)))
    return tuple(out)


def _platform_capabilities(platform: str) -> tuple[str, ...] | None:
    needle = platform.lower().replace("_", "-").replace(" ", "-")
    for pack in _iter_gateway_packs():
        for entry in pack.entries:
            if str(entry.fields.get("platform", "")).lower() == needle:
                return tuple(
                    str(c) for c in entry.fields.get("capabilities", ())
                )
    return None


def _iter_gateway_packs() -> tuple[Any, ...]:
    return domain_packs("gateways")


def assess_gateway_to_gateway(
    source_platform: str,
    target_platform: str,
    security: ApiSecurityModel | None = None,
) -> ApiMigrationIntelligence:
    """§77 gateway -> gateway capability comparison via §130 packs."""
    target_caps = _platform_capabilities(target_platform)
    observed = _observed_gateway_capabilities(security)
    unknowns: list[UnknownFact] = []
    if target_caps is None:
        unknowns.append(_unk(
            target_platform, "capability pack",
            "bundle a capability pack for the target platform"))
    if not observed:
        unknowns.append(_unk(
            source_platform, "observed gateway capabilities",
            "provide gateway config so capabilities can be detected"))
    dims: list[DimensionResult] = []
    for canon, ev in observed:
        if target_caps is None:
            dims.append(_dim(canon, MigrationClass.UNKNOWN,
                             "target capabilities unknown", evidence=ev))
            continue
        target_names = {c.lower() for c in target_caps}
        alias = _CANON_GW.get(canon, {})
        alias_name = alias.get(
            target_platform.lower().replace("_", "-").replace(" ", "-"),
            canon,
        )
        if canon in target_names or alias_name in target_names:
            dims.append(_dim(
                canon, MigrationClass.DIRECT,
                f"target declares {alias_name or canon}", evidence=ev,
                preserved=(canon,)))
        else:
            dims.append(_dim(
                canon, MigrationClass.NO_EQUIVALENT,
                f"target {target_platform} lists no {canon} capability",
                evidence=ev, lost=(canon,)))
    return ApiMigrationIntelligence(
        kind=MigrationKind.GATEWAY_TO_GATEWAY,
        source=source_platform, target=target_platform,
        assessments=(_assessment(
            f"{source_platform}->{target_platform}",
            MigrationKind.GATEWAY_TO_GATEWAY, dims),)
        if dims else (),
        unknowns=tuple(unknowns),
    )


# --------------------------------------------------------- contract versions

# §82 feature detection on the OpenAPI model -> required target feature.
_FEATURE_DETECTORS: tuple[
    tuple[str, Callable[[OpenApiProjectModel], bool]], ...
] = (
    ("webhooks", lambda m: bool(m.webhooks)),
    ("callbacks", lambda m: bool(m.callbacks)),
)


def _uses_type_lists(model: OpenApiProjectModel) -> bool:
    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            if isinstance(node.get("type"), list):
                return True
            if "nullable" in node and isinstance(
                    node.get("type"), list):
                return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False
    return any(walk(s.content) for s in model.schemas)


def _uses_nullable(model: OpenApiProjectModel) -> bool:
    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            if node.get("nullable") is True:
                return True
            return any(walk(v) for v in node.values())
        if isinstance(node, list):
            return any(walk(v) for v in node)
        return False
    return any(walk(s.content) for s in model.schemas)


def _feature_targets(family: str) -> frozenset[str]:
    entry = _OAS_PACK.entry(f"openapi-{family}")
    if entry is None:
        return frozenset()
    feats = set(str(f) for f in entry.fields.get("features", ()))
    if family in {"3.0", "3.1", "3.2"}:
        feats.update({"callbacks", "links", "examples"})
    if family in {"3.1", "3.2"}:
        feats.update({"webhooks", "json-schema-2020-12", "mutualTLS"})
    if family == "3.2":
        feats.update({"additionalOperations", "query-method"})
    return frozenset(feats)


# feature -> (class when target lacks it, note)
_NO_EQUIV_FEATURES = {
    "webhooks": ("first-class webhook declarations", ),
    "mutualTLS": ("mutualTLS security scheme type", ),
    "query-method": ("QUERY method operations", ),
    "additionalOperations": ("additionalOperations support", ),
}


def assess_contract_version(
    openapi: OpenApiProjectModel,
    target_family: str,
) -> ApiMigrationIntelligence:
    """§82 OpenAPI family migration (e.g. 3.0 -> 3.1) via pack features."""
    source_family = version_family(openapi.schema_version) or "unknown"
    target_features = _feature_targets(target_family)
    dims: list[DimensionResult] = []

    if _feature_targets(source_family) and not _feature_targets(
            target_family):
        dims.append(_dim(
            "target family", MigrationClass.UNKNOWN,
            f"no knowledge pack features for family {target_family}",
            unknowns=(_unk(target_family, "pack feature data",
                           "extend the openapi versions pack"),)))

    feature_uses: list[tuple[str, str]] = []
    for feat, detect in _FEATURE_DETECTORS:
        if detect(openapi):
            feature_uses.append((feat, feat))
    if _uses_nullable(openapi):
        feature_uses.append(("nullable", "nullable schema keyword"))
    if _uses_type_lists(openapi):
        feature_uses.append(
            ("json-schema-2020-12", "type:[...] union keyword"))
    if any(s.type.lower() == "mutualtls"
           for s in openapi.security_schemes if s.type):
        feature_uses.append(("mutualTLS", "mutualTLS security scheme"))
    if any(o.method.lower() == "query" for o in openapi.operations):
        feature_uses.append(("query-method", "QUERY method operation"))

    for feat, detail in feature_uses:
        if feat == "nullable" and "json-schema-2020-12" in target_features:
            dims.append(_dim(
                feat, MigrationClass.APPROXIMATE,
                "nullable:true maps to type:[T,null] union",
                lost=("nullable keyword form",)))
        elif feat in target_features:
            dims.append(_dim(
                feat, MigrationClass.DIRECT,
                f"{detail} supported by OpenAPI {target_family}",
                preserved=(feat,)))
        elif feat == "json-schema-2020-12":
            dims.append(_dim(
                feat, MigrationClass.REDESIGN_REQUIRED,
                "JSON Schema 2020-12 dialect requires schema rewrite for "
                f"OpenAPI {target_family}",
                lost=("2020-12 schema dialect",)))
        elif feat in _NO_EQUIV_FEATURES:
            dims.append(_dim(
                feat, MigrationClass.NO_EQUIVALENT,
                f"{_NO_EQUIV_FEATURES[feat][0]} have no equivalent in "
                f"OpenAPI {target_family}",
                lost=(feat,)))
        else:
            dims.append(_dim(
                feat, MigrationClass.UNKNOWN,
                f"{detail}: target family support not recorded in pack",
                unknowns=(_unk(feat, "target family feature data",
                               "extend the openapi versions pack"),)))

    if not dims:
        dims.append(_dim(
            "dialect features", MigrationClass.DIRECT,
            "no version-sensitive features detected in the contract"))

    return ApiMigrationIntelligence(
        kind=MigrationKind.CONTRACT_VERSION,
        source=f"openapi-{source_family}", target=f"openapi-{target_family}",
        assessments=(_assessment(
            f"openapi {source_family} -> {target_family}",
            MigrationKind.CONTRACT_VERSION, dims),),
    )


# ------------------------------------------------------------ v1 -> v2 / sdk


def client_generation_impact(diff: ContractDiff) -> tuple[SdkImpact, ...]:
    """§83 changes that alter generated SDK surface."""
    out: list[SdkImpact] = []
    for ch in diff.changes:
        if ch.kind == "unresolvable":
            out.append(SdkImpact(
                subject=ch.subject, kind=ch.kind, affects_sdk=None,
                detail=ch.detail,
                evidence=_ev(ch.location, ch.detail)))
            continue
        out.append(SdkImpact(
            subject=ch.subject, kind=ch.kind, affects_sdk=True,
            detail=ch.detail, evidence=_ev(ch.location, ch.detail)))
    return tuple(out)


def assess_version_upgrade(
    before: OpenApiProjectModel,
    after: OpenApiProjectModel,
) -> ApiMigrationIntelligence:
    """v1 -> v2 semantic-diff driven classification (spec 008 machinery)."""
    from forge_doctor_api.checks.compat.catalog import CompatibilityClass
    diff = diff_models(before, after)
    _TO_CLASS = {
        CompatibilityClass.NON_BREAKING: MigrationClass.DIRECT,
        CompatibilityClass.POTENTIALLY_BREAKING: MigrationClass.APPROXIMATE,
        CompatibilityClass.BREAKING: MigrationClass.REDESIGN_REQUIRED,
        CompatibilityClass.UNKNOWN: MigrationClass.UNKNOWN,
    }
    by_subject: dict[str, list[DimensionResult]] = {}
    for ch in diff.changes:
        cls = _TO_CLASS[ch.classification]
        if ch.kind == "endpoint_removed":
            cls = MigrationClass.NO_EQUIVALENT
        by_subject.setdefault(ch.subject, []).append(_dim(
            ch.kind, cls, ch.detail, evidence=_ev(ch.location, ch.detail),
            lost=(ch.kind,) if cls is not MigrationClass.DIRECT else ()))
    return ApiMigrationIntelligence(
        kind=MigrationKind.VERSION_UPGRADE,
        source="v1", target="v2",
        assessments=tuple(
            _assessment(subject, MigrationKind.VERSION_UPGRADE, dims)
            for subject, dims in sorted(by_subject.items())),
        sdk_impacts=client_generation_impact(diff),
        unknowns=tuple(
            _unk(ch.path, ch.detail, "resolve contract structures")
            for ch in diff.changes if ch.kind == "unresolvable"),
    )


# ------------------------------------------------------------------ §167

def decide(
    question: DecisionQuestion,
    subject: str,
    migration: ApiMigrationIntelligence | None = None,
    capabilities: Any = None,
    remaining_clients: int | None = None,
) -> DecisionBrief:
    """§167 decision brief: facts/constraints/capabilities/tradeoffs/unknowns.

    No verdict - the caller decides.
    """
    facts: list[str] = []
    constraints: list[str] = []
    caps: list[str] = []
    tradeoffs: list[str] = []
    unknowns: list[UnknownFact] = []

    if migration is not None:
        for a in migration.assessments:
            for d in a.dimensions:
                line = f"{a.subject}: {d.dimension} -> {d.classification}"
                if d.classification is MigrationClass.DIRECT:
                    facts.append(f"{line} ({d.detail})")
                elif d.classification is MigrationClass.APPROXIMATE:
                    tradeoffs.append(f"{line} ({d.detail})")
                elif d.classification in (
                        MigrationClass.REDESIGN_REQUIRED,
                        MigrationClass.NO_EQUIVALENT):
                    constraints.append(f"{line} ({d.detail})")
                else:
                    unknowns.extend(d.unknowns)
            unknowns.extend(a.unknowns)
        unknowns.extend(migration.unknowns)

    if capabilities is not None:
        for c in getattr(capabilities, "capabilities", ()):
            caps.append(str(c.capability))
        for g in getattr(capabilities, "gaps", ()):
            constraints.append(
                f"capability gap: {g.rule} requires {g.requires}")

    if question is DecisionQuestion.CAN_RETIRE_VERSION:
        if remaining_clients is None:
            unknowns.append(_unk(
                subject, "remaining client call sites",
                "scan client repos for call sites on this version"))
        elif remaining_clients > 0:
            constraints.append(
                f"{remaining_clients} client call site(s) still observed")
        else:
            facts.append("no client call sites observed on this version")

    return DecisionBrief(
        question=question.value, subject=subject,
        facts=tuple(sorted(set(facts))),
        constraints=tuple(sorted(set(constraints))),
        capabilities=tuple(sorted(set(caps))),
        tradeoffs=tuple(sorted(set(tradeoffs))),
        unknowns=tuple(unknowns),
    )
