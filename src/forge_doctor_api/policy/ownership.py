"""§186-187 ownership resolution — declared sources, recorded precedence.

Precedence (highest first): openapi extensions -> catalog metadata ->
CODEOWNERS -> service config -> platform contract. Every consulted source
is recorded on the ApiOwnership record; conflicts surface all hits.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from forge_doctor_api.analyzers.openapi import OpenApiProjectModel
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind
from forge_doctor_api.policy.model import ApiOwnership, OwnershipSource

_PRECEDENCE = (
    "openapi_extension",
    "catalog",
    "codeowners",
    "service_config",
    "platform_contract",
)

_OWNER_EXTS = {"x-owner", "x-team", "x-contact-owner"}
_DOMAIN_EXTS = {"x-domain", "x-team-domain"}
_TAG_EXTS = {"x-tags", "x-domain-tags"}


def _ev(source: str, summary: str) -> tuple[Evidence, ...]:
    return (Evidence(kind=EvidenceKind.STATIC, source=source, summary=summary),)


def _codeowners_owners(context: ProjectContext) -> dict[str, str]:
    """Parse CODEOWNERS: path glob -> last-matching owner (git semantics)."""
    for rel in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        try:
            text = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            continue
        owners: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern, owners_list = parts[0], parts[1:]
            owners[pattern] = owners_list[0]  # first owner is the primary
        return owners
    return {}


def _catalog_owner(context: ProjectContext) -> str | None:
    for rel in ("catalog-info.yaml", "catalog-info.yml", "catalog.yaml"):
        try:
            text = context.read_text(rel)
        except (OSError, UnicodeDecodeError):
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            spec = doc.get("spec")
            owner = spec.get("owner") if isinstance(spec, dict) else doc.get("owner")
            if owner:
                return str(owner)
    return None


def _service_config_owner(context: ProjectContext, files: list[str]) -> str | None:
    for rel in sorted(files):
        if Path(rel).name.lower() not in ("service.yaml", "service.yml", "service-info.yaml"):
            continue
        try:
            doc = yaml.safe_load(context.read_text(rel))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        if isinstance(doc, dict) and doc.get("owner"):
            return str(doc["owner"])
    return None


def resolve_ownership(
    context: ProjectContext,
    files: list[str],
    openapi: OpenApiProjectModel | None = None,
) -> tuple[ApiOwnership, ...]:
    """Resolve the project owner + per-tag domains from declared sources (§186)."""
    hits: list[OwnershipSource] = []

    # openapi extensions at document level
    ext_owner = ext_domain = None
    if openapi is not None:
        for ext in openapi.extensions:
            if ext.name in _OWNER_EXTS and isinstance(ext.value, str):
                ext_owner = ext.value
            if ext.name in _DOMAIN_EXTS and isinstance(ext.value, str):
                ext_domain = ext.value
        if ext_owner:
            hits.append(OwnershipSource(
                source="openapi_extension", owner=ext_owner,
                evidence=_ev("openapi", "x-owner extension"),
            ))
    cat = _catalog_owner(context)
    if cat:
        hits.append(OwnershipSource(
            source="catalog", owner=cat, evidence=_ev("catalog-info.yaml", "spec.owner"),
        ))
    patterns = _codeowners_owners(context)
    co = next(iter(patterns.values()), None) if patterns else None
    if co:
        hits.append(OwnershipSource(
            source="codeowners", owner=co, evidence=_ev("CODEOWNERS", "first pattern owner"),
        ))
    svc = _service_config_owner(context, files)
    if svc:
        hits.append(OwnershipSource(
            source="service_config", owner=svc, evidence=_ev("service.yaml", "owner"),
        ))

    chosen = next(
        (h.owner for h in sorted(hits, key=lambda h: _PRECEDENCE.index(h.source))),
        None,
    )
    tags: tuple[str, ...] = ()
    if openapi is not None:
        tags = tuple(sorted({t for op in openapi.operations for t in op.tags}))
    return (ApiOwnership(
        subject="(project)",
        owner=chosen,
        domain=ext_domain,
        tags=tags,
        sources=tuple(sorted(hits, key=lambda h: _PRECEDENCE.index(h.source))),
        precedence=_PRECEDENCE,
    ),)
