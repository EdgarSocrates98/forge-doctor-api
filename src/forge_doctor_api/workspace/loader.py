"""§108 workspace manifest loading — declared membership only.

`forge-doctor-api.workspace.yaml` at the workspace root:

    name: payments-platform
    members:
      - name: payments-api
        path: payments-api
        role: service
      - name: payments-sdk
        path: payments-sdk
        role: client
        provides: [payments-sdk]

Member paths are resolved relative to the workspace root and must stay
inside it (§203 — no parent-dir walking, no convention discovery).
"""

from __future__ import annotations

import yaml

from forge_doctor_api.core.context import ContextError, ProjectContext
from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.workspace.model import MemberRole, Workspace, WorkspaceMember

_MANIFEST_NAMES = (
    "forge-doctor-api.workspace.yaml",
    "forge-doctor-api.workspace.yml",
    "workspace.yaml",
    "workspace.yml",
)


def _role(value: object, issues: list[str], name: str) -> MemberRole:
    if value is None:
        return MemberRole.UNKNOWN
    try:
        return MemberRole(str(value))
    except ValueError:
        issues.append(f"member {name!r} declares unknown role {value!r}")
        return MemberRole.UNKNOWN


def _parse_member(raw: object, issues: list[str]) -> WorkspaceMember | None:
    if not isinstance(raw, dict):
        issues.append("member entry is not a mapping")
        return None
    name = raw.get("name")
    path = raw.get("path")
    if not name or not path:
        issues.append("member entry missing `name` or `path`")
        return None
    provides = raw.get("provides") or ()
    if isinstance(provides, str):
        provides = (provides,)
    return WorkspaceMember(
        name=str(name),
        path=str(path),
        role=_role(raw.get("role"), issues, str(name)),
        provides=tuple(str(p) for p in provides),
    )


def load_workspace(context: ProjectContext) -> Workspace | None:
    """Load the workspace manifest; None when the project is not a workspace."""
    manifest = next((n for n in _MANIFEST_NAMES if context.exists(n)), None)
    if manifest is None:
        return None
    try:
        doc = yaml.safe_load(context.read_text(manifest))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return Workspace(
            name=context.root.name,
            issues=(f"{manifest}: unreadable or invalid YAML",),
        )
    if not isinstance(doc, dict) or not isinstance(doc.get("members"), list):
        return Workspace(
            name=context.root.name,
            issues=(f"{manifest}: not a workspace document (missing `members` list)",),
        )

    issues: list[str] = []
    unknowns: list[UnknownFact] = []
    members: list[WorkspaceMember] = []
    seen: dict[str, WorkspaceMember] = {}
    for raw in doc["members"]:
        member = _parse_member(raw, issues)
        if member is None:
            continue
        if member.name in seen:
            # role-ambiguous: same repo declared twice — first wins, recorded
            prev = seen[member.name]
            issues.append(
                f"member {member.name!r} declared twice "
                f"(roles {prev.role.value!r} vs {member.role.value!r}) — first kept"
            )
            continue
        try:
            resolved = context.resolve(member.path)
        except ContextError:
            issues.append(f"member {member.name!r} path escapes the workspace root")
            continue
        if not resolved.is_dir():
            member = WorkspaceMember(
                name=member.name, path=member.path, role=member.role,
                provides=member.provides, present=False,
            )
            issues.append(f"member {member.name!r} path {member.path!r} not found")
            unknowns.append(UnknownFact(
                subject=member.name,
                missing="declared member checkout",
                resolution="clone the member repo at the declared path",
            ))
        seen[member.name] = member
        members.append(member)

    return Workspace(
        name=str(doc.get("name") or context.root.name),
        members=tuple(members),
        issues=tuple(issues),
        unknowns=tuple(unknowns),
    )
