"""Plugin output validation — the contract a plugin result must keep.

Trust decides *what may run*; conformance checks *how it behaves*;
this module decides *what may come back*. A plugin result is data
crossing a trust boundary — the validator treats it as hostile:

- findings must be well-formed (canonical check id, known
  severity/confidence/evidence kinds, ≥1 evidence item, UNKNOWN
  confidence requires unknowns);
- entity ids must be canonical ``kind:domain:identifier``;
- ``source_location.path`` must stay inside the analyzed root —
  relative POSIX, no ``..``, no drive letters, no absolute paths;
- a declared ``schema_version`` must be a version this build emits;
- the serialized result must fit ``PLUGIN_RESULT_BUDGET`` — over
  budget is a violation, never silently accepted.

The validator works on the *serialized* dict form (``to_dict()`` for
Models, the value itself for plain containers) so a plugin cannot
smuggle a malformed object past the model layer's ``__post_init__``
checks by returning plain dicts.

Spec 084. Validation never raises: it returns a tuple of typed
``OutputViolation`` records, one per case, sorted for determinism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from forge_doctor_api.core.models import (
    CHECK_ID_PATTERN,
    Confidence,
    EvidenceKind,
    Model,
    Severity,
    parse_entity_id,
)

# Serialized-result byte budget — sized generously for a real finding
# set while keeping a hostile plugin from returning unbounded output.
PLUGIN_RESULT_BUDGET = 256 * 1024

# Schema versions this build can emit or consume. A plugin declaring
# anything else is speaking a contract we do not have.
KNOWN_SCHEMA_VERSIONS = frozenset({"1.0", "forge-contracts/1"})

_ENUMS = {
    "severity": {s.value for s in Severity},
    "confidence": {c.value for c in Confidence},
    "evidence_kind": {k.value for k in EvidenceKind},
}


@dataclass(frozen=True, kw_only=True)
class OutputViolation(Model):
    """One typed rejection of plugin output."""

    rule: str        # stable rule id, e.g. "severity", "entity-id"
    detail: str      # what was wrong, no plugin-supplied formatting
    path: str = ""   # where in the result, e.g. "findings[2]"


def _as_data(result: Any) -> Any:
    if isinstance(result, Model):
        return result.to_dict()
    if isinstance(result, (list, tuple)):
        return [x.to_dict() if isinstance(x, Model) else x
                for x in result]
    return result


def _finding_violations(f: Any, path: str,
                        root: Path) -> list[OutputViolation]:
    out: list[OutputViolation] = []
    if not isinstance(f, dict):
        return [OutputViolation(
            rule="finding-type", path=path,
            detail="finding must be a mapping")]
    fid = f.get("id")
    if not isinstance(fid, str) or not CHECK_ID_PATTERN.match(fid):
        out.append(OutputViolation(
            rule="check-id", path=f"{path}.id",
            detail="finding id must match the stable check-id shape"))
    for field, allowed in _ENUMS.items():
        val = f.get(field)
        if val not in allowed:
            out.append(OutputViolation(
                rule=field, path=f"{path}.{field}",
                detail=f"{field} must be one of "
                       f"{sorted(allowed)}"))
    evidence = f.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        out.append(OutputViolation(
            rule="evidence", path=f"{path}.evidence",
            detail="finding must carry at least one evidence item"))
    else:
        for i, ev in enumerate(evidence):
            ep = f"{path}.evidence[{i}]"
            if not isinstance(ev, dict):
                out.append(OutputViolation(
                    rule="evidence", path=ep,
                    detail="evidence must be a mapping"))
                continue
            if ev.get("kind") not in _ENUMS["evidence_kind"]:
                out.append(OutputViolation(
                    rule="evidence-kind", path=f"{ep}.kind",
                    detail="unknown evidence kind"))
            if not ev.get("source") or not ev.get("summary"):
                out.append(OutputViolation(
                    rule="evidence", path=ep,
                    detail="evidence needs source and summary"))
    if f.get("confidence") == Confidence.UNKNOWN.value and not (
            f.get("unknowns")):
        out.append(OutputViolation(
            rule="unknowns", path=f"{path}.unknowns",
            detail="UNKNOWN confidence requires unknowns"))
    for i, eid in enumerate(f.get("entity_ids") or []):
        try:
            parse_entity_id(str(eid))
        except Exception as exc:
            out.append(OutputViolation(
                rule="entity-id", path=f"{path}.entity_ids[{i}]",
                detail=f"non-canonical entity id: {exc}"))
    loc = f.get("source_location")
    if isinstance(loc, dict) and loc.get("path"):
        p = loc["path"]
        bad = (not isinstance(p, str) or "\\" in p
               or PurePosixPath(p).is_absolute() or ":" in p
               or ".." in PurePosixPath(p).parts)
        if not bad:
            resolved = (root / p).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                bad = True
        if bad:
            out.append(OutputViolation(
                rule="path-scope", path=f"{path}.source_location.path",
                detail="path must stay inside the analyzed root "
                       "(relative POSIX, no '..')"))
    version = f.get("schema_version")
    if version is not None and version not in KNOWN_SCHEMA_VERSIONS:
        out.append(OutputViolation(
            rule="schema-version", path=f"{path}.schema_version",
            detail=f"unknown schema_version {version!r}"))
    return out


def validate_plugin_output(result: Any,
                           project_root: Path | str,
                           ) -> tuple[OutputViolation, ...]:
    """Validate the serialized form of a plugin result.

    Returns sorted ``OutputViolation`` records — empty means the
    output satisfies the contract. Never raises on hostile input.
    """
    root = Path(project_root)
    out: list[OutputViolation] = []
    data = _as_data(result)
    if not isinstance(data, (dict, list)):
        return (OutputViolation(
            rule="result-type",
            detail="plugin result must be a mapping or a list"),)
    try:
        size = len(json.dumps(data, sort_keys=True,
                              default=str).encode("utf-8"))
    except Exception:
        return (OutputViolation(
            rule="serializable",
            detail="result is not JSON-serializable"),)
    if size > PLUGIN_RESULT_BUDGET:
        out.append(OutputViolation(
            rule="oversized",
            detail=f"result is {size}B over the "
                   f"{PLUGIN_RESULT_BUDGET}B budget"))
    version = (data.get("schema_version")
               if isinstance(data, dict) else None)
    if version is not None and version not in KNOWN_SCHEMA_VERSIONS:
        out.append(OutputViolation(
            rule="schema-version", path="schema_version",
            detail=f"unknown schema_version {version!r}"))
    findings = data.get("findings") if isinstance(data, dict) else None
    if findings is None and isinstance(data, list):
        findings = data
    if findings is not None:
        if not isinstance(findings, list):
            out.append(OutputViolation(
                rule="findings-type", path="findings",
                detail="findings must be a list"))
        else:
            for i, f in enumerate(findings):
                out.extend(_finding_violations(
                    f, f"findings[{i}]", root))
    return tuple(sorted(out, key=lambda v: (v.rule, v.path, v.detail)))
