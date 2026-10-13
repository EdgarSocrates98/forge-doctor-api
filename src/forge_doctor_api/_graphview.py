"""ForgeGraphView/v1 — the visualization contract for Graph Studio.

A read-only, rendering-ready projection of a forge's real graph. The
graph engines stay authoritative; this contract only *carries* their
data to a viewer without losing provenance, epistemic state or evidence
references. Layout coordinates are deliberately absent — they belong to
the visualization layer, not the model.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

GRAPHVIEW_SCHEMA = "forge/ForgeGraphView/v1"
GRAPH_DESCRIPTOR_SCHEMA = "forge/GraphDescriptor/v1"

# Epistemic states a view may carry. Engines map their own vocabulary
# onto these explicitly; unmapped states stay "unknown", never upgraded.
EPISTEMIC_STATES = (
    "observed",
    "declared",
    "planned",
    "desired",
    "inferred",
    "unknown",
)

# Capabilities an adapter may declare — only real ones.
GRAPH_CAPABILITIES = (
    "snapshots",
    "node_inspect",
    "edge_inspect",
    "neighbors",
    "paths",
    "dependency_traversal",
    "impact_analysis",
    "snapshot_diff",
    "temporal",
    "search",
    "filter",
    "export",
)


# Engine vocabulary → view vocabulary (explicit, reversible): a state an
# engine uses that has a view equivalent is translated; anything else
# stays "unknown" — never silently upgraded to observed/declared.
EPISTEMIC_TRANSLATION = {
    "explicit": "declared",
    "asserted": "declared",
    "actual": "observed",
}


def _check(state: str) -> str:
    if state in EPISTEMIC_STATES:
        return state
    return EPISTEMIC_TRANSLATION.get(state, "unknown")


@dataclass(frozen=True, kw_only=True)
class GraphDescriptor:
    """Summary of one graph a provider can expose (§1.2)."""

    graph_id: str
    provider_id: str
    domain: str
    graph_schema: str = GRAPH_DESCRIPTOR_SCHEMA
    snapshot_id: str = ""
    generated_at: str = ""
    node_count: int = 0
    edge_count: int = 0
    available_layers: tuple[str, ...] = ()
    available_queries: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, kw_only=True)
class GraphNodeView:
    """One node, with engine provenance preserved (§1.3)."""

    id: str
    kind: str
    label: str
    domain: str = ""
    source_provider: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    epistemic_state: str = "unknown"
    evidence_refs: tuple[str, ...] = ()
    snapshot_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "epistemic_state", _check(self.epistemic_state))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, kw_only=True)
class GraphEdgeView:
    """One directed edge; direction and semantics preserved (§1.4)."""

    id: str
    source: str
    target: str
    kind: str
    direction: str = "directed"
    provenance: str = "unknown"
    epistemic_state: str = "unknown"
    evidence_refs: tuple[str, ...] = ()
    confidence: float | None = None
    temporal: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "epistemic_state", _check(self.epistemic_state))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.confidence is None:
            d.pop("confidence")
        return d


@dataclass(frozen=True, kw_only=True)
class ForgeGraphView:
    """A complete view document: descriptor + nodes + edges."""

    descriptor: GraphDescriptor
    nodes: tuple[GraphNodeView, ...] = ()
    edges: tuple[GraphEdgeView, ...] = ()
    schema: str = GRAPHVIEW_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "descriptor": self.descriptor.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @staticmethod
    def from_dict(doc: dict[str, Any]) -> ForgeGraphView:
        d = doc["descriptor"]
        descriptor = GraphDescriptor(
            **{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()}
        )
        nodes = tuple(
            GraphNodeView(
                **{k: tuple(v) if isinstance(v, list) else v for k, v in n.items()}
            )
            for n in doc.get("nodes", [])
        )
        edges = tuple(
            GraphEdgeView(
                **{k: tuple(v) if isinstance(v, list) else v for k, v in e.items()}
            )
            for e in doc.get("edges", [])
        )
        return ForgeGraphView(descriptor=descriptor, nodes=nodes, edges=edges)


def new_descriptor(*, provider_id: str, domain: str, graph_id: str | None = None,
                   capabilities: tuple[str, ...] = (),
                   limitations: tuple[str, ...] = ()) -> GraphDescriptor:
    """A descriptor with real provenance stamps."""
    return GraphDescriptor(
        graph_id=graph_id or f"graph-{uuid.uuid4().hex[:8]}",
        provider_id=provider_id,
        domain=domain,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        capabilities=tuple(c for c in capabilities if c in GRAPH_CAPABILITIES),
        limitations=limitations,
    )
