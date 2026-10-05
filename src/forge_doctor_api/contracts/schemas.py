"""Published JSON Schemas for ``forge-contracts/1`` — vendored verbatim.

Pure data — the cross-doctor wire contract in a form any implementation
(Python or not) can validate against. Each schema describes the
*contract-normalized* shape emitted by ``ContractModel.to_dict()``;
``x-*`` extension keys are always allowed.

Provenance: canonical definitions from the ``forge-contracts/1`` wire
contract (the same published shapes the Data Doctor ships). Vendored —
not imported — so neither doctor depends on the other's package at
runtime (spec 074).
"""

from __future__ import annotations

from typing import Any

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_ID_BASE = "https://forge-contracts.dev/schemas/forge-contracts/1"
_VERSION_FIELD = {
    "type": "string",
    "pattern": r"^forge-contracts/\d+$",
    "description": "Contract family/major this payload was written against.",
}

_FINDING: dict[str, Any] = {
    "type": "object",
    "required": ["check_id", "title", "severity", "category", "message"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "check_id": {"type": "string"},
        "title": {"type": "string"},
        "severity": {"enum": ["error", "warning", "info", "pass"]},
        "category": {"type": "string"},
        "message": {"type": "string"},
        "fingerprint": {"type": ["string", "null"]},
        "file": {"type": ["string", "null"]},
        "line": {"type": ["integer", "null"]},
        "column": {"type": ["integer", "null"]},
        "end_line": {"type": ["integer", "null"]},
        "end_column": {"type": ["integer", "null"]},
        "recommendation": {"type": ["string", "null"]},
        "confidence": {"type": ["string", "null"]},
        "evidence": {"type": ["string", "null"]},
        "evidence_kind": {"type": ["string", "null"]},
        "source": {"type": ["string", "null"]},
        "fixable": {"type": ["boolean", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_ENTITY: dict[str, Any] = {
    "type": "object",
    "required": ["id", "kind", "domain"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "id": {"type": "string"},
        "kind": {"type": "string"},
        "domain": {"type": "string"},
        "identifier": {"type": "string"},
        "name": {"type": "string"},
        "file": {"type": ["string", "null"]},
        "line": {"type": ["integer", "null"]},
        "attrs": {"type": "object"},
    },
    "additionalProperties": True,
}

_RELATIONSHIP: dict[str, Any] = {
    "type": "object",
    "required": ["src", "dst", "kind"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "src": {"type": "string"},
        "dst": {"type": "string"},
        "kind": {"type": "string"},
        "evidence_kind": {"type": ["string", "null"]},
        "attrs": {"type": "object"},
    },
    "additionalProperties": True,
}

_EVIDENCE: dict[str, Any] = {
    "type": "object",
    "required": ["ref", "kind", "source"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "ref": {"type": "string"},
        "kind": {"type": "string"},
        "source": {"type": "string"},
        "detail": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

_CAPABILITY: dict[str, Any] = {
    "type": "object",
    "required": ["id", "domain", "status"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "id": {"type": "string"},
        "domain": {"type": "string"},
        "status": {"type": "string"},
        "confidence": {"type": ["string", "null"]},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_UNKNOWN_FACT: dict[str, Any] = {
    "type": "object",
    "required": ["subject", "kind", "reason"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "subject": {"type": "string"},
        "kind": {"type": "string"},
        "reason": {"type": "string"},
        "source": {"type": ["string", "null"]},
        "detail": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

_MIGRATION_PLAN: dict[str, Any] = {
    "type": "object",
    "required": ["id", "source", "target", "kind"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "id": {"type": "string"},
        "source": {"type": "string"},
        "target": {"type": "string"},
        "kind": {"type": "string"},
        "readiness": {"type": ["string", "null"]},
        "steps": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_REMEDIATION_PLAN: dict[str, Any] = {
    "type": "object",
    "required": ["id", "check_id", "problem"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "id": {"type": "string"},
        "check_id": {"type": "string"},
        "problem": {"type": "string"},
        "targets": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "items": {"type": ["string", "object"]},
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "requires_approval": {"type": "boolean"},
    },
    "additionalProperties": True,
}

HANDOFF: dict[str, Any] = {
    "$schema": SCHEMA_DIALECT,
    "$id": f"{_ID_BASE}/handoff.json",
    "title": "forge-contracts/1 handoff bundle (contract-normalized form)",
    "type": "object",
    "required": ["tool", "project", "summary"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "tool": {
            "type": "object",
            "required": ["name", "version"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
            },
        },
        "project": {"type": "object"},
        "summary": {"type": "object"},
        "findings": {"type": "array", "items": _FINDING},
        "entities": {"type": "array", "items": _ENTITY},
        "relationships": {"type": "array", "items": _RELATIONSHIP},
        "capabilities": {"type": "array", "items": _CAPABILITY},
        "plans": {"type": "array", "items": _REMEDIATION_PLAN},
        "unknowns": {"type": "array", "items": _UNKNOWN_FACT},
    },
    "additionalProperties": True,
}

DIAGNOSTIC_MANIFEST: dict[str, Any] = {
    "$schema": SCHEMA_DIALECT,
    "$id": f"{_ID_BASE}/diagnostic-manifest.json",
    "title": "forge-contracts/1 diagnostic manifest (summary-first entry point)",
    "type": "object",
    "required": ["tool"],
    "properties": {
        "contract_version": _VERSION_FIELD,
        "tool": {
            "type": "object",
            "required": ["name", "version"],
            "properties": {
                "name": {"type": "string"},
                "version": {"type": "string"},
            },
        },
        "domains": {"type": "array", "items": {"type": "string"}},
        "entity_count": {"type": "integer"},
        "finding_count": {"type": "integer"},
        "unknown_count": {"type": "integer"},
        "risks": {"type": "array", "items": {"type": "object"}},
        "capabilities": {"type": "array", "items": _CAPABILITY},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}


def _wrap(kind: str, body: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": f"{_ID_BASE}/{kind}.json",
        "title": title,
        **body,
    }


FORGE_CONTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "entity": _wrap("entity", _ENTITY, "forge-contracts/1 entity"),
    "relationship": _wrap(
        "relationship", _RELATIONSHIP, "forge-contracts/1 relationship"),
    "evidence": _wrap("evidence", _EVIDENCE, "forge-contracts/1 evidence"),
    "finding": _wrap("finding", _FINDING, "forge-contracts/1 finding"),
    "capability": _wrap(
        "capability", _CAPABILITY, "forge-contracts/1 capability"),
    "unknown-fact": _wrap(
        "unknown-fact", _UNKNOWN_FACT,
        "forge-contracts/1 unknown fact (honest UNKNOWN)"),
    "migration-plan": _wrap(
        "migration-plan", _MIGRATION_PLAN,
        "forge-contracts/1 migration plan"),
    "remediation-plan": _wrap(
        "remediation-plan", _REMEDIATION_PLAN,
        "forge-contracts/1 remediation plan"),
    "handoff": HANDOFF,
    "diagnostic-manifest": DIAGNOSTIC_MANIFEST,
}
