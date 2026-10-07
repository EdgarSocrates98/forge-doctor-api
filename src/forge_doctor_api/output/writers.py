"""§175 output writers — console stays in the CLI; these emit portable text.

Every export carries §174 metadata (schema_version, tool_version,
knowledge_versions). SARIF is emitted only for location-anchored findings
(§176): findings without a source location are counted in `skipped`, never
forced into a fake location.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from forge_doctor_api import __version__
from forge_doctor_api.core.export import SCHEMA_VERSION, export_findings
from forge_doctor_api.core.models import Finding, Severity
from forge_doctor_api.knowledge import knowledge_versions

_SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
_SARIF_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def write_json(findings: Iterable[Finding]) -> str:
    """Versioned JSON envelope (§174)."""
    return json.dumps(export_findings(findings).to_dict(),
                      indent=2, sort_keys=True)


def write_jsonl(findings: Iterable[Finding]) -> str:
    """One finding per line; first line is the §174 metadata record."""
    export = export_findings(findings)
    meta = {
        "_meta": True,
        "schema_version": export.schema_version,
        "tool_version": export.tool_version,
        "knowledge_versions": export.knowledge_versions,
    }
    lines = [json.dumps(meta, sort_keys=True)]
    lines.extend(
        json.dumps(f.to_dict(), sort_keys=True) for f in export.findings
    )
    return "\n".join(lines) + "\n"


def write_sarif(findings: Iterable[Finding]) -> str:
    """SARIF 2.1.0 for location-anchored findings (§176)."""
    export = export_findings(findings)
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    skipped = 0
    for f in export.findings:
        rules.setdefault(f.id, {
            "id": f.id,
            "name": f.title,
            "shortDescription": {"text": f.title},
            "properties": {
                "severity": f.severity.value,
                "confidence": f.confidence.value,
            },
        })
        if f.source_location is None:
            skipped += 1
            continue
        loc: dict[str, Any] = {
            "artifactLocation": {"uri": f.source_location.path},
        }
        if f.source_location.line is not None:
            loc["region"] = {"startLine": f.source_location.line}
        results.append({
            "ruleId": f.id,
            "level": _SARIF_LEVEL.get(f.severity, "note"),
            "message": {"text": f.description},
            "locations": [{"physicalLocation": loc}],
            "properties": {
                "confidence": f.confidence.value,
                "entity_ids": list(f.entity_ids),
            },
        })
    doc = {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "forge-doctor-api",
                    "version": __version__,
                    "rules": [rules[k] for k in sorted(rules)],
                },
            },
            "results": results,
            "properties": {
                "schema_version": SCHEMA_VERSION,
                "tool_version": __version__,
                "knowledge_versions": knowledge_versions(),
                "skipped_no_location": skipped,
            },
        }],
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def write_agent(
    findings: Iterable[Finding],
    unknowns: Iterable[Any] = (),
) -> str:
    """Agent-compact format: metadata comment + one line per finding."""
    export = export_findings(findings)
    lines = [
        f"# schema_version={export.schema_version} "
        f"tool_version={export.tool_version}",
        "# knowledge_versions=" + ",".join(
            f"{k}@{v}" for k, v in sorted(export.knowledge_versions.items())),
    ]
    for f in export.findings:
        subject = f.entity_ids[0] if f.entity_ids else (
            f.source_location.path if f.source_location else "-")
        line = f.source_location.line if f.source_location else None
        desc = " ".join(f.description.split())
        lines.append(
            f"{f.id}|{f.severity.value}|{f.confidence.value}|{subject}"
            f"{':' + str(line) if line else ''}|{desc}"
        )
    for u in unknowns:
        lines.append(f"UNKNOWN|{u.subject}|{u.missing}")
    return "\n".join(lines) + "\n"


WRITERS = {
    "json": write_json,
    "jsonl": write_jsonl,
    "sarif": write_sarif,
    "agent": write_agent,
}
