"""Per-member model assembly for fleet aggregation (§110-§115).

Each present member repo is scanned under its own `ProjectContext`;
absent members contribute UNKNOWN entries, never silently dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.version import ApiVersionModel, detect_version_model
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind
from forge_doctor_api.policy import ApiOwnership, resolve_ownership
from forge_doctor_api.reliability import ApiReliabilityModel, load_reliability_model
from forge_doctor_api.security import ApiSecurityModel, load_security_model
from forge_doctor_api.twin.drift import gateway_routes
from forge_doctor_api.workspace.model import MemberRole, Workspace, WorkspaceMember

_YAML_JSON = {".yaml", ".yml", ".json"}
_GRAPHQL = {".graphql", ".gql"}
_PROTO = {".proto"}


@dataclass(frozen=True, kw_only=True)
class MemberData:
    """One member repo's loaded models + detected surface."""

    member: WorkspaceMember
    files: tuple[str, ...] = ()
    openapi: OpenApiProjectModel | None = None
    security: ApiSecurityModel | None = None
    reliability: ApiReliabilityModel | None = None
    version: ApiVersionModel | None = None
    ownership: tuple[ApiOwnership, ...] = ()
    styles: tuple[str, ...] = ()
    gateway_routes: dict[str, str] | None = None


def _ev(source: str, summary: str) -> Evidence:
    return Evidence(kind=EvidenceKind.STATIC, source=source, summary=summary)


def _head_is_asyncapi(text: str) -> bool:
    return bool(re.search(r"^\s*asyncapi\s*:", text[:4000]))


def _detect_styles(files: tuple[str, ...], context: ProjectContext) -> tuple[str, ...]:
    """Cheap strong-marker style detection for §111 portfolio counts."""
    styles: set[str] = set()
    for rel in files:
        suffix = Path(rel).suffix.lower()
        if suffix in _PROTO:
            styles.add("grpc")
            continue
        if suffix in _GRAPHQL:
            styles.add("graphql")
            continue
        if suffix in _YAML_JSON:
            try:
                head = context.read_text(rel)[:4000]
            except (OSError, UnicodeDecodeError):
                continue
            if _head_is_asyncapi(head):
                styles.add("async")
            elif re.search(r'^\s*"?openapi"?\s*:', head) or '"openapi"' in head:
                styles.add("rest")
            elif suffix == ".json" and "__schema" in head:
                styles.add("graphql")
            try:
                doc_head = json.loads(head) if suffix == ".json" else None
                if isinstance(doc_head, dict) and "__schema" in doc_head:
                    styles.add("graphql")
            except (ValueError, json.JSONDecodeError):
                pass
    return tuple(sorted(styles))


def member_context(context: ProjectContext, member: WorkspaceMember) -> ProjectContext:
    return ProjectContext.from_root(context.resolve(member.path), clock=context.clock)


def collect_member(
    context: ProjectContext, member: WorkspaceMember
) -> MemberData:
    """Load the analyzable surface of one member repo."""
    ctx = member_context(context, member)
    files = tuple(ctx.iter_files())
    openapi = load_openapi_project(ctx)
    security = load_security_model(ctx, list(files), openapi=openapi)
    reliability = load_reliability_model(ctx, list(files))
    version = detect_version_model(openapi)
    ownership = resolve_ownership(ctx, list(files), openapi)
    styles = _detect_styles(files, ctx)
    if member.role is MemberRole.GATEWAY:
        styles = tuple(sorted(set(styles) | {"gateway"}))
    routes = gateway_routes(ctx, list(files)) if member.role is MemberRole.GATEWAY else {}
    return MemberData(
        member=member, files=files, openapi=openapi, security=security,
        reliability=reliability, version=version, ownership=ownership,
        styles=styles, gateway_routes=routes,
    )


def collect_all(
    context: ProjectContext, workspace: Workspace
) -> dict[str, MemberData]:
    """Per-member data for every present member, in manifest order."""
    return {
        m.name: collect_member(context, m)
        for m in workspace.members
        if m.present
    }


def collect_handoff(member: WorkspaceMember, handoff: Any) -> MemberData:
    """Spec 070: ingest a `ForgeHandoff` as a member's fleet record.

    Only compact report-equivalent fields are kept — style hints from
    detected capabilities, plus nothing else. Every model field the
    handoff cannot evidence stays ``None`` so downstream aggregation
    reports it as unknown rather than fabricated.
    """
    from forge_doctor_api.handoff.boundary import (
        handoff_to_member_fields,
    )
    fields = handoff_to_member_fields(handoff)
    styles: tuple[str, ...] = fields["styles"]
    if member.role is MemberRole.GATEWAY:
        styles = tuple(sorted(set(styles) | {"gateway"}))
    return MemberData(
        member=member,
        styles=styles,
    )


def operations(data: MemberData) -> list[OpenApiOperation]:
    if data.openapi is None:
        return []
    return [o for o in data.openapi.operations if o.source is OperationSource.PATH]


def sanitize_host(host: str) -> str:
    """§115 strip credentials/query from an external host string."""
    cleaned = re.sub(r"//[^/@]*@", "//", host)  # userinfo
    return cleaned.split("?", 1)[0].split("#", 1)[0].rstrip("/")
