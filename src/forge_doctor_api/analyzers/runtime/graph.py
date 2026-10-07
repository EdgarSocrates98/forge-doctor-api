"""Observed-traffic graph materialization (§8, §28-29).

Executions' downstream calls produce `service -[CALLS]-> service` edges
with RUNTIME evidence; observed resends add `RETRIES` edges. These edges
are *observed* traffic, never static guesses — callers/callees that
cannot be resolved produce no edge.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.runtime.execution import (
    DownstreamCall,
    RequestExecution,
)
from forge_doctor_api.core.graph import ServiceGraph
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceKind,
    Relationship,
    RelationshipKind,
    entity_id,
)


def runtime_graph(executions: tuple[RequestExecution, ...]) -> ServiceGraph:
    """CALLS/RETRIES edges from observed downstream calls only."""
    graph = ServiceGraph()
    seen: set[tuple[str, str, str]] = set()
    for ex in executions:
        for call in ex.downstream_calls:
            caller = call.caller or ex.service
            callee = call.callee
            if caller is None or callee is None:
                continue
            src = entity_id(EntityKind.SERVICE, "runtime", caller)
            dst = entity_id(EntityKind.SERVICE, "runtime", callee)
            graph.add_entity(
                Entity(id=src, kind=EntityKind.SERVICE, name=caller)
            )
            graph.add_entity(
                Entity(id=dst, kind=EntityKind.SERVICE, name=callee)
            )
            key = (src, dst, RelationshipKind.CALLS)
            if key not in seen:
                seen.add(key)
                graph.add_relationship(
                    Relationship(
                        kind=RelationshipKind.CALLS,
                        source_id=src,
                        target_id=dst,
                        confidence=Confidence.MEDIUM,
                        evidence=(
                            Evidence(
                                kind=EvidenceKind.RUNTIME,
                                source=_src(call),
                                summary=(
                                    f"observed {caller} -> {callee} "
                                    f"({call.operation})"
                                ),
                            ),
                        ),
                    )
                )
            if call.retries:
                rkey = (src, dst, RelationshipKind.RETRIES)
                if rkey not in seen:
                    seen.add(rkey)
                    graph.add_relationship(
                        Relationship(
                            kind=RelationshipKind.RETRIES,
                            source_id=src,
                            target_id=dst,
                            confidence=Confidence.MEDIUM,
                            evidence=(
                                Evidence(
                                    kind=EvidenceKind.RUNTIME,
                                    source=_src(call),
                                    summary=(
                                        f"observed {call.retries} resend(s) "
                                        f"{caller} -> {callee}"
                                    ),
                                ),
                            ),
                        )
                    )
    return graph


def _src(call: DownstreamCall) -> str:
    return call.evidence[0].source if call.evidence else "(runtime)"
