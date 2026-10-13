"""Spec 057 — graph slices + edge export."""

from __future__ import annotations

from forge_doctor_api.core.graph import (
    Direction,
    ServiceGraph,
    export_edges,
    slice_graph,
)
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    Evidence,
    EvidenceKind,
    Relationship,
)


def _ev(src: str) -> tuple[Evidence, ...]:
    return (Evidence(kind=EvidenceKind.STATIC, source=src,
                     summary="declared"),)


def _graph() -> ServiceGraph:
    ents = [Entity(id=f"service:python:{n}", kind="service", name=n)
            for n in ("a", "b", "c", "d")]
    rels = [
        Relationship(kind="CALLS", source_id="service:python:a",
                     target_id="service:python:b",
                     confidence=Confidence.HIGH, evidence=_ev("a.py")),
        Relationship(kind="CALLS", source_id="service:python:b",
                     target_id="service:python:c",
                     confidence=Confidence.HIGH, evidence=_ev("b.py")),
        Relationship(kind="DEPENDS_ON", source_id="service:python:c",
                     target_id="service:python:d",
                     confidence=Confidence.HIGH, evidence=_ev("c.py")),
    ]
    return ServiceGraph(entities=ents, relationships=rels)


class TestSliceGraph:
    def test_depth_bounded(self) -> None:
        g = _graph()
        s = slice_graph(g, "service:python:a", depth=1,
                        direction=Direction.OUT)
        assert {n.id for n in s.nodes} == {
            "service:python:a", "service:python:b"}
        assert s.boundary_ids == ("service:python:b",)
        assert len(s.edges) == 1 and s.edges[0].evidence

    def test_direction_filter(self) -> None:
        g = _graph()
        s = slice_graph(g, "service:python:c", depth=1,
                        direction=Direction.IN)
        assert {n.id for n in s.nodes} == {
            "service:python:b", "service:python:c"}

    def test_deeper_reaches_boundary(self) -> None:
        g = _graph()
        s = slice_graph(g, "service:python:a", depth=2,
                        direction=Direction.OUT)
        assert {n.id for n in s.nodes} == {
            "service:python:a", "service:python:b", "service:python:c"}
        assert s.boundary_ids == ("service:python:c",)

    def test_evidence_preserved(self) -> None:
        s = slice_graph(_graph(), "service:python:a", depth=3)
        assert all(e.evidence for e in s.edges)

    def test_unknown_root_empty_plus_unknown(self) -> None:
        s = slice_graph(_graph(), "service:python:ghost")
        assert s.nodes == () and s.unknowns

    def test_deterministic(self) -> None:
        g = _graph()
        assert slice_graph(g, "service:python:a", depth=3) == \
            slice_graph(g, "service:python:a", depth=3)


class TestEdgeExport:
    def test_exports_carry_evidence_and_confidence(self) -> None:
        edges = export_edges(_graph())
        assert len(edges) == 3
        e = next(e for e in edges
                 if e.from_id == "service:python:a")
        assert e.kind == "CALLS"
        assert e.confidence is Confidence.HIGH
        assert e.evidence_ids == ("STATIC:a.py",)

    def test_sorted_output(self) -> None:
        edges = export_edges(_graph())
        keys = [(e.from_id, e.kind, e.to_id) for e in edges]
        assert keys == sorted(keys)
