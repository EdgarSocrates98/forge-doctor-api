"""Forge Doctor API → Obsidian verification report projection.

Composes a sanitized ``theforge/ObsidianNoteRef/v1`` note for independent
API contract/drift verifications.  Projection only — the vendored
``forge_doctor_api._forge_obsidian`` engine owns vault bytes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from forge_doctor_api._forge_obsidian.notes import build_note_ref, section_yaml

FORGE_ID = "forge-doctor-api"


def build_obsidian_verification_report(
    *,
    title: str,
    summary: str,
    workspace: str,
    vault_id: str,
    findings: Iterable[Mapping[str, Any]] | None = None,
    drift: Iterable[Mapping[str, Any]] | None = None,
    evidence: Iterable[Mapping[str, Any]] | None = None,
    related_refs: Iterable[str] | None = None,
    note_path: str | None = None,
    confidence: str = "unknown",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a verification report note (findings + drift + evidence)."""
    return build_note_ref(
        forge_id=FORGE_ID,
        title=title,
        summary=summary,
        workspace=workspace,
        vault_id=vault_id,
        kind="verification-report",
        body_sections=[
            section_yaml("Findings", list(findings or [])),
            section_yaml("Drift", list(drift or [])),
            section_yaml("Evidence", list(evidence or [])),
        ],
        note_path=note_path,
        confidence=confidence,
        tags=["api", "doctor", "verification"],
        related=list(related_refs or []),
        provenance=provenance,
    )


__all__ = ["FORGE_ID", "build_obsidian_verification_report"]
