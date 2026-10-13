"""Forge Doctor API → ForgeGraphView/v1 adapter.

Projects the ServiceGraph (entities + evidence-backed relationships —
edges are never inferred by construction) onto the view contract.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api._graphview import (
    ForgeGraphView,
    GraphEdgeView,
    GraphNodeView,
    new_descriptor,
)

PROVIDER = "forge-doctor-api"


def build_view(path: str | Path) -> ForgeGraphView | None:
    """ServiceGraph of a target dir → view. None when it can't be built."""
    from forge_doctor_api.service_graph import build_service_graph

    try:
        g = build_service_graph(Path(path).resolve())
    except Exception:
        return None
    entities = list(g.entities())
    if not entities:
        return None
    rels = list(g.relationships())
    desc = new_descriptor(
        provider_id=PROVIDER,
        domain="api-diagnostics",
        graph_id="service-graph",
        capabilities=(
            "node_inspect",
            "edge_inspect",
            "neighbors",
            "dependency_traversal",
            "impact_analysis",
            "search",
            "filter",
            "export",
        ),
        limitations=("built on demand from contract+impl+client evidence",),
    )
    object.__setattr__(desc, "node_count", len(entities))
    object.__setattr__(desc, "edge_count", len(rels))
    object.__setattr__(
        desc, "available_layers", tuple(sorted({e.kind for e in entities}))
    )
    nodes = tuple(
        GraphNodeView(
            id=e.id,
            kind=e.kind,
            label=e.name,
            domain="api-diagnostics",
            source_provider=PROVIDER,
            attributes=dict(e.attributes),
            epistemic_state="observed",
        )
        for e in entities
    )
    edges = tuple(
        GraphEdgeView(
            id="|".join(r.key),
            source=r.source_id,
            target=r.target_id,
            kind=r.kind,
            provenance="observed",
            epistemic_state="observed",
            evidence_refs=tuple(ev.source for ev in r.evidence),
            confidence={
                "HIGH": 1.0,
                "MEDIUM": 0.66,
                "LOW": 0.33,
            }.get(r.confidence.value),
            attributes={"confidence": r.confidence.value},
        )
        for r in rels
    )
    return ForgeGraphView(descriptor=desc, nodes=nodes, edges=edges)
