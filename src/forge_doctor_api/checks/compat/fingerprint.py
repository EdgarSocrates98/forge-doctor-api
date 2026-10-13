"""Semantic fingerprints (§180).

A contract's fingerprint is a SHA-256 over a canonical projection of the
`OpenApiProjectModel`: all formatting, comments, YAML key order, file
locations and line numbers are erased, so two serializations of the same
*semantic* contract share one fingerprint. This is what baselines and
`contract diff` short-circuit on; identical fingerprints imply an empty diff.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel, OperationSource


def _canon(value: Any) -> Any:
    """Normalize dicts to sorted-key lists and sets/tuples to sorted lists."""
    if isinstance(value, dict):
        return {k: _canon(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, list | tuple | frozenset | set):
        items = [_canon(v) for v in value]
        return sorted(items, key=lambda i: json.dumps(i, sort_keys=True, default=str))
    return value


def _projection(model: OpenApiProjectModel) -> dict[str, Any]:
    ops = [
        {
            "method": o.method,
            "path": o.path,
            "operation_id": o.operation_id,
            "deprecated": o.deprecated,
            "tags": list(o.tags),
            "parameters": sorted(o.parameter_pointers),
            "request_body": o.request_body_pointer,
            "responses": sorted(o.response_pointers),
            "has_security": o.has_security,
        }
        for o in model.operations
        if o.source is OperationSource.PATH
    ]
    return {
        "documents": [
            {
                "openapi": d.openapi_version,
                "title": d.title,
                "version": d.api_version,
            }
            for d in model.documents
        ],
        "servers": [
            {"url": s.url, "description": s.description} for s in model.servers
        ],
        "operations": ops,
        "parameters": [
            {
                "pointer": p.pointer,
                "name": p.name,
                "in": p.location_in,
                "required": p.required,
                "schema": _canon(p.schema),
            }
            for p in model.parameters
        ],
        "request_bodies": [
            {
                "pointer": b.pointer,
                "required": b.required,
                "content_types": list(b.content_types),
                "schema_shapes": list(b.schema_shapes),
            }
            for b in model.request_bodies
        ],
        "responses": [
            {
                "pointer": r.pointer,
                "status": r.status,
                "content_types": list(r.content_types),
                "schema_shapes": list(r.schema_shapes),
                "headers": list(r.header_names),
            }
            for r in model.responses
        ],
        "schemas": [
            {"name": s.name, "content": _canon(s.content)} for s in model.schemas
        ],
        "security_requirements": [
            {
                "owner": r.owner_pointer,
                "schemes": sorted(
                    {"name": s.name, "scopes": sorted(s.scopes)} for s in r.schemes
                ),
            }
            for r in model.security_requirements
        ],
        "security_schemes": [
            {
                "name": s.name,
                "type": s.type,
                "scheme": s.scheme,
                "bearer_format": s.bearer_format,
                "in": s.location_in,
            }
            for s in model.security_schemes
        ],
    }


def semantic_fingerprint(model: OpenApiProjectModel) -> str:
    """Return the stable sha256 fingerprint of the model's semantic content."""
    canonical = _canon(_projection(model))
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
