"""OAS### check engine (§11).

Consumes an `OpenApiProjectModel` and returns `Finding`s — no I/O, no clock,
no network. Checks are functions `(model, index) -> Iterable[Finding]` held in
`CHECKS` in id order, so output ordering never depends on evaluation order.

Judgment-dependent checks (OAS010, OAS016, OAS017, OAS020) emit LOW-confidence
candidates with `UnknownFact`s rather than asserting violations (§101, §145).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forge_doctor_api.analyzers.openapi.model import (
    CycleKind,
    DocumentStatus,
    OpenApiExtension,
    OpenApiOperation,
    OpenApiParameter,
    OpenApiProjectModel,
    OpenApiResponse,
    RefStatus,
)
from forge_doctor_api.checks.oas.catalog import BY_ID, CheckSpec
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    SourceLocation,
    UnknownFact,
)

_PATH_PARAM = re.compile(r"\{([^{}/]+)\}")
_ENV_LOCAL = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|\[?::1\]?)|\.(local|localhost|internal|lan|test|invalid|example)$"
)
_ENV_DEV = re.compile(r"(^|[.\-_])dev(elopment|el)?([.\-_]|$)|sandbox", re.IGNORECASE)
_ENV_STAGING = re.compile(
    r"(^|[.\-_])(stg|stage|staging|qa|uat|preprod|preview)([.\-_]|$)", re.IGNORECASE
)
_PRIVATE_IP = re.compile(
    r"^(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}$|^\d{1,3}(\.\d{1,3}){3}$"
)
_HOST = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://(?P<host>[^/?:{]+)")

# Keys whose subtrees are user data — never scanned for schema keywords.
_DATA_SUBTREES = frozenset(
    {"example", "examples", "default", "enum", "const", "value", "dataValue", "serializedValue"}
)

_SUNSET_EXTENSION = re.compile(r"^x-(sunset|deprecat)", re.IGNORECASE)
_SUNSET_HEADER = re.compile(r"^(sunset|deprecation)$", re.IGNORECASE)

_TYPE_INFO_KEYS = frozenset(
    {
        "type",
        "$ref",
        "properties",
        "items",
        "enum",
        "const",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "format",
        "additionalProperties",
        "patternProperties",
        "prefixItems",
    }
)


def _entity_id(kind: str, path: str, pointer: str) -> str:
    return f"{kind}:openapi:{path}#{pointer}"


def _evidence(location: SourceLocation, summary: str) -> tuple[Evidence, ...]:
    return (
        Evidence(
            kind=EvidenceKind.STATIC,
            source=location.path,
            summary=summary,
            line=location.line,
        ),
    )


def _finding(
    spec: CheckSpec,
    *,
    description: str,
    location: SourceLocation,
    entity_ids: Sequence[str] = (),
    severity: Severity | None = None,
    confidence: Confidence | None = None,
    remediation: str | None = None,
    unknowns: Sequence[UnknownFact] = (),
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity if severity is None else severity,
        confidence=spec.confidence if confidence is None else confidence,
        evidence_kind=spec.evidence_kind,
        evidence=_evidence(location, description),
        entity_ids=tuple(entity_ids),
        source_location=location,
        remediation=remediation,
        unknowns=tuple(unknowns),
    )


@dataclass(frozen=True)
class _Index:
    """Precomputed lookups so individual checks never re-scan the model."""

    model: OpenApiProjectModel
    parameters: Mapping[tuple[str, str], OpenApiParameter]
    responses: Mapping[tuple[str, str], OpenApiResponse]
    extensions: Mapping[str, tuple[OpenApiExtension, ...]]
    requirements_by_doc: Mapping[str, tuple[Any, ...]]
    parsed_docs: tuple[str, ...]
    referenced: frozenset[tuple[str, str]]

    @classmethod
    def build(cls, model: OpenApiProjectModel) -> _Index:
        extensions: dict[str, list[OpenApiExtension]] = {}
        for ext in model.extensions:
            extensions.setdefault(ext.location.path, []).append(ext)
        requirements: dict[str, list[Any]] = {}
        for req in model.security_requirements:
            requirements.setdefault(req.location.path, []).append(req)
        return cls(
            model=model,
            parameters={(p.location.path, p.pointer): p for p in model.parameters},
            responses={(r.location.path, r.pointer): r for r in model.responses},
            extensions={k: tuple(v) for k, v in extensions.items()},
            requirements_by_doc={k: tuple(v) for k, v in requirements.items()},
            parsed_docs=tuple(
                d.location.path for d in model.documents if d.status is DocumentStatus.PARSED
            ),
            referenced=frozenset(
                (r.target_path, r.target_pointer)
                for r in model.references
                if r.status is RefStatus.RESOLVED
                and r.target_path is not None
                and r.target_pointer is not None
            ),
        )

    def op_parameters(self, op: OpenApiOperation) -> tuple[OpenApiParameter, ...]:
        return tuple(
            self.parameters[(op.location.path, pointer)]
            for pointer in op.parameter_pointers
            if (op.location.path, pointer) in self.parameters
        )

    def op_responses(self, op: OpenApiOperation) -> tuple[OpenApiResponse, ...]:
        return tuple(
            self.responses[(op.location.path, pointer)]
            for pointer in op.response_pointers
            if (op.location.path, pointer) in self.responses
        )

    def doc_requirements(self, path: str, owner: str = "") -> tuple[Any, ...]:
        return tuple(
            r for r in self.requirements_by_doc.get(path, ()) if r.owner_pointer == owner
        )


def _op_entity(op: OpenApiOperation) -> str:
    return f"operation:openapi:{op.identity}"


def _doc_entity(path: str) -> str:
    return f"api:openapi:{path}"


# -- OAS001 .. OAS010 ---------------------------------------------------------


def _oas001(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS001"]
    reasons = {
        DocumentStatus.MALFORMED: ("document is not parseable as YAML/JSON", Severity.HIGH),
        DocumentStatus.UNREADABLE: ("document cannot be read", Severity.HIGH),
        DocumentStatus.INVALID_VERSION: (
            "`openapi` is not a MAJOR.MINOR.PATCH string",
            Severity.HIGH,
        ),
        DocumentStatus.UNSUPPORTED_VERSION: (
            "specification version is outside the supported knowledge pack",
            Severity.MEDIUM,
        ),
    }
    for doc in model.documents:
        reason = reasons.get(doc.status)
        if reason is None:
            continue
        text, severity = reason
        version = f" {doc.openapi_version!r}" if doc.openapi_version else ""
        yield _finding(
            spec,
            description=f"{doc.location.path}: {text}{version}",
            location=doc.location,
            entity_ids=(_doc_entity(doc.location.path),),
            severity=severity,
            remediation="fix the document so it parses as a supported OpenAPI version",
        )


def _oas002(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS002"]
    for ref in model.references:
        if ref.status not in (RefStatus.MISSING, RefStatus.INVALID):
            continue
        what = "malformed reference" if ref.status is RefStatus.INVALID else "target not found"
        yield _finding(
            spec,
            description=f"{ref.keyword} {ref.ref!r} at {ref.pointer}: {what}",
            location=ref.location,
            entity_ids=(_entity_id("api", ref.location.path, ref.pointer),),
            remediation="point the reference at an existing in-project target",
        )


def _oas003(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS003"]
    seen: dict[str, list[OpenApiOperation]] = {}
    for op in model.operations:
        if op.operation_id:
            seen.setdefault(op.operation_id, []).append(op)
    for operation_id in sorted(seen):
        ops = seen[operation_id]
        if len(ops) < 2:
            continue
        sites = ", ".join(f"{o.location.path}#{o.pointer}" for o in ops)
        yield _finding(
            spec,
            description=f"operationId {operation_id!r} names {len(ops)} operations: {sites}",
            location=ops[0].location,
            entity_ids=tuple(_op_entity(o) for o in ops),
            remediation="give each operation a unique operationId",
        )


def _oas004(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS004"]
    for op in model.operations:
        if op.source.value != "PATH" or op.operation_id:
            continue
        yield _finding(
            spec,
            description=f"{op.method} {op.path} has no operationId",
            location=op.location,
            entity_ids=(_op_entity(op),),
            remediation="add a unique operationId",
        )


def _oas005(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS005"]
    for response in model.responses:
        if response.description is not None or response.ref is not None:
            continue
        yield _finding(
            spec,
            description=f"response at {response.pointer} has no description",
            location=response.location,
            entity_ids=(
                _entity_id("response", response.location.path, response.pointer),
            ),
            remediation="add a description to the response object",
        )
    for op in model.operations:
        if not op.response_pointers:
            yield _finding(
                spec,
                description=f"{op.method} {op.path} declares no responses",
                location=op.location,
                entity_ids=(_op_entity(op),),
                remediation="declare at least one response for the operation",
            )


def _oas006(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS006"]
    for op in model.operations:
        responses = index.op_responses(op)
        if not responses or len(responses) != len(op.response_pointers):
            continue
        if all(r.status == "default" for r in responses):
            yield _finding(
                spec,
                description=f"{op.method} {op.path} declares only a default response",
                location=op.location,
                entity_ids=(_op_entity(op),),
                remediation="document explicit success and error status codes",
            )


def _oas007(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS007"]
    ops_by_doc: dict[str, list[OpenApiOperation]] = {}
    for op in model.operations:
        ops_by_doc.setdefault(op.location.path, []).append(op)
    for path in sorted(ops_by_doc):
        shaped: list[tuple[OpenApiOperation, tuple[str, ...]]] = []
        for op in ops_by_doc[path]:
            shapes = tuple(
                sorted(
                    {
                        shape
                        for r in index.op_responses(op)
                        if r.status is not None and r.status[:1] in ("4", "5")
                        for shape in r.schema_shapes
                    }
                )
            )
            if shapes:
                shaped.append((op, shapes))
        if len(shaped) < 3:
            continue
        counts: dict[tuple[str, ...], int] = {}
        for _, shapes in shaped:
            counts[shapes] = counts.get(shapes, 0) + 1
        dominant = max(counts.values())
        if dominant < len(shaped) * 0.6 or len(counts) < 2:
            continue
        majority = {s for s, n in counts.items() if n == dominant}
        deviants = sorted(
            (op for op, shapes in shaped if shapes not in majority),
            key=lambda o: o.identity,
        )
        first = deviants[0]
        yield _finding(
            spec,
            description=(
                f"{path}: {len(deviants)} of {len(shaped)} operations with error schemas use "
                f"a different 4xx/5xx shape than the dominant one: "
                + ", ".join(o.identity for o in deviants)
            ),
            location=first.location,
            entity_ids=tuple(_op_entity(o) for o in deviants),
            remediation="align error responses on one documented error schema",
        )


def _oas008(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS008"]
    for body in model.request_bodies:
        if body.has_schema:
            continue
        if body.ref is not None and not body.content_types:
            continue  # unresolved ref: schema presence is UNKNOWN
        yield _finding(
            spec,
            description=f"request body at {body.pointer} has no schema in its content",
            location=body.location,
            entity_ids=(_entity_id("schema", body.location.path, body.pointer),),
            remediation="declare a schema for the request body content",
        )


def _oas009(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS009"]
    for response in model.responses:
        if response.has_schema or not response.content_types:
            continue
        yield _finding(
            spec,
            description=(
                f"response {response.status or 'component'} at {response.pointer} declares "
                f"content without a schema"
            ),
            location=response.location,
            entity_ids=(_entity_id("response", response.location.path, response.pointer),),
            remediation="declare a schema for each media type in the response content",
        )


def _oas010(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS010"]
    ops_by_doc: dict[str, int] = {}
    for op in model.operations:
        ops_by_doc[op.location.path] = ops_by_doc.get(op.location.path, 0) + 1
    for path in index.parsed_docs:
        if not ops_by_doc.get(path):
            continue
        requirements = index.doc_requirements(path)
        if requirements and any(r.schemes for r in requirements):
            continue
        ops = [o for o in model.operations if o.location.path == path]
        if ops and all(
            any(r.schemes for r in index.doc_requirements(path, owner=o.pointer))
            for o in ops
        ):
            continue  # every operation carries its own named requirement
        doc = next(d for d in model.documents if d.location.path == path)
        yield _finding(
            spec,
            description=(
                f"{path}: no document-level security requirement protects "
                f"{ops_by_doc[path]} operations"
            ),
            location=doc.location,
            entity_ids=(_doc_entity(path),),
            unknowns=(
                UnknownFact(
                    subject=path,
                    missing="API exposure classification (internal/partner/public)",
                    resolution=(
                        "declare exposure via gateway/org metadata or add a security "
                        "requirement so the question is moot"
                    ),
                ),
            ),
            remediation=(
                "if this API is partner/public, add a document-level `security` requirement"
            ),
        )


# -- OAS011 .. OAS020 ---------------------------------------------------------


def _oas011(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS011"]
    schemes_by_doc: dict[str, set[str]] = {}
    for scheme in model.security_schemes:
        schemes_by_doc.setdefault(scheme.location.path, set()).add(scheme.name)
    for req in model.security_requirements:
        defined = schemes_by_doc.get(req.location.path, set())
        missing = sorted(s.name for s in req.schemes if s.name not in defined)
        if missing:
            yield _finding(
                spec,
                description=(
                    f"security requirement at {req.pointer} references undeclared "
                    f"scheme(s): {', '.join(missing)}"
                ),
                location=req.location,
                entity_ids=(_entity_id("api", req.location.path, req.pointer),),
                confidence=Confidence.HIGH,
                remediation="define the scheme under components.securitySchemes",
            )
    for op in model.operations:
        if not op.has_security:
            continue
        parent = index.doc_requirements(op.location.path)
        if not parent or not any(r.schemes for r in parent):
            continue
        own = index.doc_requirements(op.location.path, owner=op.pointer)
        if any(r.schemes for r in own):
            continue
        yield _finding(
            spec,
            description=(
                f"{op.method} {op.path} replaces the document security requirement with "
                "anonymous access"
            ),
            location=op.location,
            entity_ids=(_op_entity(op),),
            remediation="confirm the opt-out is intended, or remove the empty `security`",
        )


def _template_vars(path: str) -> frozenset[str]:
    return frozenset(_PATH_PARAM.findall(path))


def _oas012_oas013(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec12 = BY_ID["OAS012"]
    spec13 = BY_ID["OAS013"]
    for op in model.operations:
        if op.source.value != "PATH":
            continue
        variables = _template_vars(op.path)
        declared = index.op_parameters(op)
        named = {p.name: p for p in declared if p.name is not None}
        for var in sorted(variables - set(named)):
            yield _finding(
                spec13,
                description=(
                    f"{op.method} {op.path}: template variable {{{var}}} has no parameter "
                    "declaration"
                ),
                location=op.location,
                entity_ids=(_op_entity(op),),
                remediation=f"declare a required `in: path` parameter named {var!r}",
            )
        for name in sorted(named):
            param = named[name]
            if param.location_in == "path":
                if name not in variables:
                    yield _finding(
                        spec12,
                        description=(
                            f"{op.method} {op.path}: parameter {name!r} is declared "
                            "`in: path` but absent from the path template"
                        ),
                        location=param.location,
                        entity_ids=(_op_entity(op),),
                        remediation="rename the parameter or fix the path template",
                    )
                elif not param.required:
                    yield _finding(
                        spec12,
                        description=(
                            f"{op.method} {op.path}: path parameter {name!r} is declared "
                            "without required: true"
                        ),
                        location=param.location,
                        entity_ids=(_op_entity(op),),
                        remediation="set required: true on the path parameter",
                    )
            elif name in variables:
                yield _finding(
                    spec12,
                    description=(
                        f"{op.method} {op.path}: parameter {name!r} appears in the path "
                        f"template but is declared in: {param.location_in}"
                    ),
                    location=param.location,
                    entity_ids=(_op_entity(op),),
                    remediation="declare the parameter in: path",
                )


def _oas014(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS014"]
    for schema in model.schemas:
        content = schema.content
        if not isinstance(content, dict):
            continue
        if _TYPE_INFO_KEYS & set(content):
            continue
        yield _finding(
            spec,
            description=f"component schema {schema.name!r} carries no type information",
            location=schema.location,
            entity_ids=(_entity_id("schema", schema.location.path, schema.pointer),),
            remediation="add type/properties or a composition keyword to the schema",
        )


def _oas015(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS015"]
    for op in model.operations:
        if not op.deprecated:
            continue
        item_pointer = op.pointer.rsplit("/", 1)[0]
        owners = {"", item_pointer, op.pointer}
        marked = any(
            _SUNSET_EXTENSION.match(ext.name)
            for ext in index.extensions.get(op.location.path, ())
            if ext.owner_pointer in owners
        )
        marked = marked or any(
            _SUNSET_HEADER.match(header)
            for response in index.op_responses(op)
            for header in response.header_names
        )
        if marked:
            continue
        yield _finding(
            spec,
            description=f"{op.method} {op.path} is deprecated without sunset metadata",
            location=op.location,
            entity_ids=(_op_entity(op),),
            remediation="add x-sunset metadata or a Sunset/Deprecation response header",
        )


def _env_class(url: str) -> str | None:
    if "{" in url:
        return None  # parameterized server URL
    match = _HOST.match(url.strip())
    host = match["host"].lower() if match else url.strip().split("/", 1)[0].lower()
    if _ENV_LOCAL.search(host) or _PRIVATE_IP.match(host):
        return "local"
    if _ENV_STAGING.search(host):
        return "staging"
    if _ENV_DEV.search(host):
        return "dev"
    return "other"


def _oas016(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS016"]
    servers_by_doc: dict[str, list[Any]] = {}
    for server in model.servers:
        servers_by_doc.setdefault(server.location.path, []).append(server)
    for path in sorted(servers_by_doc):
        classes = {
            cls for server in servers_by_doc[path] if (cls := _env_class(server.url)) is not None
        }
        if len(classes) < 2:
            continue
        urls = ", ".join(sorted(s.url for s in servers_by_doc[path]))
        yield _finding(
            spec,
            description=(
                f"{path}: server URLs span environments {sorted(classes)}: {urls}"
            ),
            location=servers_by_doc[path][0].location,
            entity_ids=(_doc_entity(path),),
            unknowns=(
                UnknownFact(
                    subject=path,
                    missing="environment policy for the API",
                    resolution="declare environments via gateway/deployment config",
                ),
            ),
            remediation="split per-environment server documents or use server variables",
        )


def _oas017(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS017"]

    def walk(node: Any) -> int:
        count = 0
        if isinstance(node, dict):
            if node.get("additionalProperties") is True or node.get("additionalProperties") == {}:
                count += 1
            for key, value in node.items():
                if isinstance(key, str) and (key in _DATA_SUBTREES or key.startswith("x-")):
                    continue
                count += walk(value)
        elif isinstance(node, list):
            for item in node:
                count += walk(item)
        return count

    for schema in model.schemas:
        hits = walk(schema.content)
        if not hits:
            continue
        yield _finding(
            spec,
            description=(
                f"component schema {schema.name!r} allows unrestricted additionalProperties "
                f"at {hits} site(s)"
            ),
            location=schema.location,
            entity_ids=(_entity_id("schema", schema.location.path, schema.pointer),),
            unknowns=(
                UnknownFact(
                    subject=schema.name,
                    missing="whether arbitrary payload keys are intended",
                    resolution="confirm the map contract or constrain additionalProperties",
                ),
            ),
            remediation="set additionalProperties to false or a bounded schema if unintended",
        )


def _oas018(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS018"]
    for schema in model.schemas:
        if (schema.location.path, schema.pointer) in index.referenced:
            continue
        yield _finding(
            spec,
            description=f"component schema {schema.name!r} is never referenced",
            location=schema.location,
            entity_ids=(_entity_id("schema", schema.location.path, schema.pointer),),
            remediation="remove the schema or reference it",
        )


def _oas019(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS019"]
    for cycle in model.cycles:
        if cycle.kind is CycleKind.ALIAS:
            yield _finding(
                spec,
                description=(
                    f"reference cycle cannot resolve to a concrete object: "
                    f"{' -> '.join(cycle.members)}"
                ),
                location=cycle.location,
                entity_ids=(_entity_id("api", cycle.location.path, cycle.pointer),),
                remediation="break the alias chain with a concrete schema",
            )
        else:
            yield _finding(
                spec,
                confidence=Confidence.MEDIUM,
                severity=Severity.INFO,
                description=(
                    f"recursive reference structure (consumers must bound depth): "
                    f"{' -> '.join(cycle.members)}"
                ),
                location=cycle.location,
                entity_ids=(_entity_id("api", cycle.location.path, cycle.pointer),),
            )


def _oas020(model: OpenApiProjectModel, index: _Index) -> Iterator[Finding]:
    spec = BY_ID["OAS020"]
    for op in model.operations:
        if op.source.value != "PATH" or op.tags:
            continue
        yield _finding(
            spec,
            description=f"{op.method} {op.path} has no tags or domain grouping",
            location=op.location,
            entity_ids=(_op_entity(op),),
            unknowns=(
                UnknownFact(
                    subject=op.identity,
                    missing="domain/owner attribution for the operation",
                    resolution="add tags or declare ownership metadata",
                ),
            ),
        )


CHECKS: tuple[Any, ...] = (
    _oas001,
    _oas002,
    _oas003,
    _oas004,
    _oas005,
    _oas006,
    _oas007,
    _oas008,
    _oas009,
    _oas010,
    _oas011,
    _oas012_oas013,
    _oas014,
    _oas015,
    _oas016,
    _oas017,
    _oas018,
    _oas019,
    _oas020,
)


def run_openapi_checks(model: OpenApiProjectModel) -> tuple[Finding, ...]:
    """Run every OAS check over a parsed model; deterministic output order."""
    index = _Index.build(model)
    findings = [finding for check in CHECKS for finding in check(model, index)]
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                f.id,
                f.source_location.path if f.source_location else "",
                f.source_location.line or 0 if f.source_location else 0,
                f.description,
            ),
        )
    )
