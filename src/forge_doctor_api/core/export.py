"""Versioned finding export envelope (§174).

Every exported payload carries `schema_version` (shape of this envelope and
the finding contract), `tool_version` (the producing build), and
`knowledge_versions` (the bundled pack editions the findings were evaluated
against). Findings are sorted so that producer iteration order never leaks
into output; serialization inherits redaction from `Model.to_dict`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from forge_doctor_api import __version__
from forge_doctor_api.core.models import Finding, Model, ModelError, _require_text
from forge_doctor_api.knowledge.loader import knowledge_versions

SCHEMA_VERSION = "1.0"

_SCHEMA_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+$")


@dataclass(frozen=True, kw_only=True)
class FindingsExport(Model):
    schema_version: str
    tool_version: str
    knowledge_versions: dict[str, str] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        _require_text("FindingsExport.tool_version", self.tool_version)
        if not isinstance(self.schema_version, str) or not _SCHEMA_VERSION_PATTERN.match(
            self.schema_version
        ):
            raise ModelError(
                f"FindingsExport.schema_version must be 'MAJOR.MINOR': {self.schema_version!r}"
            )


def _finding_order(finding: Finding) -> tuple[str, tuple[str, ...], str]:
    return (finding.id, finding.entity_ids, finding.to_json())


def export_findings(findings: Iterable[Finding]) -> FindingsExport:
    """Wrap findings in a versioned envelope, in deterministic order."""
    return FindingsExport(
        schema_version=SCHEMA_VERSION,
        tool_version=__version__,
        knowledge_versions=knowledge_versions(),
        findings=tuple(sorted(findings, key=_finding_order)),
    )
