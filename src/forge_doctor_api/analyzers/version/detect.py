"""Version + lifecycle detection over `OpenApiProjectModel` (§18, §19, §7.4)."""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.version.model import (
    ApiVersion,
    ApiVersionModel,
    DeprecationModel,
    LifecycleState,
    VersionMechanism,
)
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    SourceLocation,
    UnknownFact,
)

_URI_VERSION = re.compile(r"(?:^|/)v(\d+(?:\.\d+)*)(?=/|$)")
_VND_VERSION = re.compile(r"vnd\.[^+;]*\.v(\d+(?:\.\d+)*)", re.I)
_MEDIA_PARAM = re.compile(r";\s*(?:version|v)\s*=\s*\"?([^\s;\"]+)", re.I)
_HEADER_VERSION = re.compile(r"^(?:api|accept|x-api)[-_]?version$", re.I)
_LIFECYCLE_KEYS = frozenset({"x-lifecycle", "x-status", "x-api-status"})
_LIFECYCLE_MAP = {
    "experimental": LifecycleState.EXPERIMENTAL,
    "beta": LifecycleState.EXPERIMENTAL,
    "alpha": LifecycleState.EXPERIMENTAL,
    "preview": LifecycleState.EXPERIMENTAL,
    "active": LifecycleState.ACTIVE,
    "ga": LifecycleState.ACTIVE,
    "stable": LifecycleState.ACTIVE,
    "deprecated": LifecycleState.DEPRECATED,
    "sunset": LifecycleState.SUNSET,
    "eol": LifecycleState.RETIRED,
    "retired": LifecycleState.RETIRED,
    "removed": LifecycleState.RETIRED,
}


def _ev(path: str, summary: str, line: int | None = None) -> Evidence:
    return Evidence(kind=EvidenceKind.STATIC, source=path, summary=summary, line=line)


def _uri_versions(model: OpenApiProjectModel) -> list[ApiVersion]:
    out: list[ApiVersion] = []
    for op in model.operations:
        for match in _URI_VERSION.finditer(op.path):
            out.append(
                ApiVersion(
                    identifier=f"v{match.group(1)}",
                    mechanism=VersionMechanism.URI,
                    evidence=(_ev(op.location.path, f"URI version segment in {op.path}"),),
                    location=op.location,
                )
            )
    for server in model.servers:
        for match in _URI_VERSION.finditer(server.url):
            out.append(
                ApiVersion(
                    identifier=f"v{match.group(1)}",
                    mechanism=VersionMechanism.URI,
                    evidence=(
                        _ev(server.location.path, f"URI version segment in {server.url}"),
                    ),
                    location=server.location,
                )
            )
    return out


def _header_versions(model: OpenApiProjectModel) -> list[ApiVersion]:
    out: list[ApiVersion] = []
    for param in model.parameters:
        if param.location_in != "header" or not param.name:
            continue
        if not _HEADER_VERSION.match(param.name):
            continue
        identifier = _header_value(param.schema)
        out.append(
            ApiVersion(
                identifier=identifier or "?",
                mechanism=VersionMechanism.HEADER,
                evidence=(
                    _ev(
                        param.location.path,
                        f"header version parameter {param.name!r}",
                    ),
                ),
                location=param.location,
            )
        )
    return out


def _header_value(schema: object) -> str | None:
    if not isinstance(schema, dict):
        return None
    for key in ("const", "default"):
        value = schema.get(key)
        if isinstance(value, str):
            return value
    enum = schema.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return str(enum[0])
    return None


def _media_versions(model: OpenApiProjectModel) -> list[ApiVersion]:
    out: list[ApiVersion] = []
    seen: set[tuple[str, str]] = set()
    containers = list(model.request_bodies) + list(model.responses)
    for item in containers:
        for media in item.content_types:
            match = _VND_VERSION.search(media) or _MEDIA_PARAM.search(media)
            if not match:
                continue
            key = (match.group(1), media)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                ApiVersion(
                    identifier=match.group(1),
                    mechanism=VersionMechanism.MEDIA_TYPE,
                    evidence=(_ev(item.location.path, f"media type version in {media}"),),
                    location=item.location,
                )
            )
    return out


def _extension_values(
    model: OpenApiProjectModel,
) -> dict[str, tuple[str, SourceLocation]]:
    values: dict[str, tuple[str, SourceLocation]] = {}
    for ext in model.extensions:
        name = ext.name.lower()
        if isinstance(ext.value, str) and name not in values:
            values[name] = (ext.value, ext.location)
        elif isinstance(ext.value, bool) and name not in values:
            values[name] = ("true" if ext.value else "false", ext.location)
    return values


def _deprecation(model: OpenApiProjectModel) -> tuple[DeprecationModel, list[Evidence]]:
    ext = _extension_values(model)
    deprecated_ops = [op for op in model.operations if op.deprecated]
    evidence: list[Evidence] = []
    if deprecated_ops:
        evidence.append(
            _ev(
                deprecated_ops[0].location.path,
                f"{len(deprecated_ops)} operation(s) marked deprecated",
            )
        )
    dep_marker = ext.get("x-deprecated")
    if dep_marker and dep_marker[0] == "true":
        evidence.append(_ev(dep_marker[1].path, "x-deprecated: true", dep_marker[1].line))
    dep_date = ext.get("x-deprecation") or ext.get("x-deprecation-date")
    sunset = ext.get("x-sunset") or ext.get("x-sunset-date")
    replacement = ext.get("x-replacement") or ext.get("x-replaced-by")
    for key, entry in (
        ("x-deprecation(-date)", dep_date),
        ("x-sunset(-date)", sunset),
        ("x-replacement", replacement),
    ):
        if entry:
            value, loc = entry
            evidence.append(_ev(loc.path, f"{key}: {value}", loc.line))
    deprecated = (
        bool(deprecated_ops)
        or (dep_marker is not None and dep_marker[0] == "true")
        or dep_date is not None
    )
    model_out = DeprecationModel(
        deprecated=deprecated,
        deprecation_date=dep_date[0] if dep_date else None,
        sunset_date=sunset[0] if sunset else None,
        replacement=replacement[0] if replacement else None,
        evidence=tuple(evidence),
    )
    return model_out, evidence


def _lifecycle(
    model: OpenApiProjectModel, deprecation: DeprecationModel
) -> tuple[LifecycleState, list[Evidence]]:
    ext = _extension_values(model)
    for key in sorted(_LIFECYCLE_KEYS):
        entry = ext.get(key)
        if entry and entry[0].lower() in _LIFECYCLE_MAP:
            value, loc = entry
            state = _LIFECYCLE_MAP[value.lower()]
            return state, [_ev(loc.path, f"{key}: {value}", loc.line)]
    evidence: list[Evidence] = []
    if deprecation.sunset_date:
        evidence.extend(deprecation.evidence)
        return LifecycleState.SUNSET, evidence
    if deprecation.deprecated:
        evidence.extend(deprecation.evidence)
        return LifecycleState.DEPRECATED, evidence
    return LifecycleState.UNKNOWN, []


def detect_version_model(model: OpenApiProjectModel) -> ApiVersionModel:
    versions = _uri_versions(model) + _header_versions(model) + _media_versions(model)
    deprecation, _ = _deprecation(model)
    lifecycle, lifecycle_evidence = _lifecycle(model, deprecation)
    unknowns = [
        UnknownFact(
            subject="lifecycle",
            missing="clients_remaining / traffic_remaining",
            resolution="requires runtime evidence ingestion (spec 014)",
        )
    ]
    if not versions:
        unknowns.append(
            UnknownFact(
                subject="versioning",
                missing="URI/header/media-type version signal",
                resolution="the contract carries no detectable version mechanism",
            )
        )
    return ApiVersionModel(
        versions=tuple(
            sorted(
                versions,
                key=lambda v: (
                    v.mechanism.value,
                    v.identifier,
                    v.location.path if v.location else "",
                ),
            )
        ),
        lifecycle=lifecycle,
        lifecycle_evidence=tuple(lifecycle_evidence),
        deprecation=deprecation,
        unknowns=tuple(unknowns),
    )
