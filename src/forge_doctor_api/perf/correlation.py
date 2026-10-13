"""Change -> runtime correlation (§38, §90, §227).

Correlates change events (from diff tooling or spec 020) with runtime
regressions on shared entities. Output records a correlation - the
model deliberately carries no "caused by" language (§227).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
)

CORRELATION_CAVEAT = (
    "correlation observed in the same scope; causality is not "
    "established by this engine"
)


@dataclass(frozen=True, kw_only=True)
class ChangeEvent(Model):
    """A semantic/contract change to correlate with runtime evidence."""

    change_id: str
    subject: str
    kind: str
    entities: tuple[str, ...] = ()
    window: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RuntimeCorrelation(Model):
    """One change<->regression correlation - never a causal claim."""

    change: str
    regression: str
    shared_entities: tuple[str, ...]
    caveat: str = CORRELATION_CAVEAT
    confidence: Confidence = Confidence.LOW
    evidence: tuple[Evidence, ...] = ()


def _finding_entities(f: Finding) -> set[str]:
    ents = set(f.entity_ids)
    if f.source_location is not None and f.source_location.path != "(runtime)":
        ents.add(f.source_location.path)
    return ents


def correlate_changes(
    changes: tuple[ChangeEvent, ...],
    regressions: tuple[Finding, ...],
) -> tuple[RuntimeCorrelation, ...]:
    """Join change events to regression findings on shared entities.

    Entity overlap is required - a bare time correlation is not
    emitted.
    """
    out: list[RuntimeCorrelation] = []
    for change in changes:
        c_ent = set(change.entities)
        if change.subject:
            c_ent.add(change.subject)
        for reg in regressions:
            shared = c_ent & _finding_entities(reg)
            if not shared:
                continue
            out.append(
                RuntimeCorrelation(
                    change=f"{change.kind}: {change.subject}",
                    regression=f"{reg.id}: {reg.title}",
                    shared_entities=tuple(sorted(shared)),
                    evidence=(
                        Evidence(
                            kind=EvidenceKind.DERIVED,
                            source="(correlation)",
                            summary=f"{change.subject} correlates with "
                            f"{reg.id} on {', '.join(sorted(shared))}",
                        ),
                    ),
                )
            )
    out.sort(key=lambda c: (c.change, c.regression))
    return tuple(out)
