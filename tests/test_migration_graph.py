"""Spec 060 — migration dependency graph over declared evidence."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind
from forge_doctor_api.migrate.graph import (
    MigrationEdge,
    MigrationEdgeKind,
    MigrationGraph,
    MigrationNode,
    Readiness,
    build_migration_graph,
    migration_paths,
)


def _model(tmp_path: Path, doc: str, name: str = "openapi.yaml"):
    (tmp_path / name).write_text(doc, "utf-8")
    ctx = ProjectContext.from_root(tmp_path)
    return load_openapi_project(ctx)


TWO_OPS_SHARED_SCHEMA = """
openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /pets:
    get:
      operationId: listPets
      responses:
        '200':
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Pet'}
    post:
      operationId: createPet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Pet'}
      responses: {'201': {description: ok}}
components:
  schemas:
    Pet: {type: object, properties: {id: {type: integer}}}
"""

VERSIONED = """
openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /v1/items:
    get: {operationId: v1Items, responses: {'200': {description: ok}}}
  /v2/items:
    get: {operationId: v2Items, responses: {'200': {description: ok}}}
"""


def test_schema_dep_edge_from_declared_pointer(tmp_path: Path) -> None:
    g = build_migration_graph(_model(tmp_path, TWO_OPS_SHARED_SCHEMA))
    edges = [e for e in g.edges
             if e.kind is MigrationEdgeKind.SCHEMA_DEP]
    assert edges, "shared declared schema must link operations"
    assert all(e.evidence for e in edges)


def test_name_similarity_never_edges(tmp_path: Path) -> None:
    doc = """
openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /users:
    get: {operationId: listUsers, responses: {'200': {description: ok}}}
  /usersAdmin:
    get: {operationId: listAdmins, responses: {'200': {description: ok}}}
"""
    g = build_migration_graph(_model(tmp_path, doc))
    assert g.edges == ()


def test_version_dep_edge(tmp_path: Path) -> None:
    g = build_migration_graph(_model(tmp_path, VERSIONED))
    vedges = [e for e in g.edges
              if e.kind is MigrationEdgeKind.VERSION_DEP]
    assert len(vedges) == 1
    assert vedges[0].from_id == "GET /v1/items"
    assert vedges[0].to_id == "GET /v2/items"
    assert vedges[0].evidence


def test_every_edge_has_evidence(tmp_path: Path) -> None:
    g = build_migration_graph(_model(tmp_path, TWO_OPS_SHARED_SCHEMA))
    assert all(e.evidence for e in g.edges)


def test_paths_deterministic(tmp_path: Path) -> None:
    a = migration_paths(build_migration_graph(
        _model(tmp_path, TWO_OPS_SHARED_SCHEMA, "a.yaml")))
    b = migration_paths(build_migration_graph(
        _model(tmp_path, TWO_OPS_SHARED_SCHEMA, "b.yaml")))
    assert [p.units for p in a] == [p.units for p in b]


def test_cycle_reported_not_broken() -> None:
    # Synthetic cycle: pairwise schema-dep edges are directional a->b,
    # so a real cycle needs a hand-built graph to exercise the contract.
    ev = (Evidence(kind=EvidenceKind.STATIC, source="t", summary="t"),)
    g = MigrationGraph(
        nodes=(
            MigrationNode(unit_id="A", readiness=Readiness.READY),
            MigrationNode(unit_id="B", readiness=Readiness.READY),
        ),
        edges=(
            MigrationEdge(from_id="A", to_id="B",
                          kind=MigrationEdgeKind.SCHEMA_DEP, evidence=ev),
            MigrationEdge(from_id="B", to_id="A",
                          kind=MigrationEdgeKind.SCHEMA_DEP, evidence=ev),
        ))
    paths = migration_paths(g)
    cyclic = [p for p in paths if not p.ordering_known]
    assert cyclic, "cycle must surface as unknown ordering"
    assert set(cyclic[0].units) == {"A", "B"}


def test_blockers_recorded(tmp_path: Path) -> None:
    doc = """
openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /old:
    get:
      operationId: oldOp
      deprecated: true
      responses: {'200': {description: ok}}
"""
    g = build_migration_graph(_model(tmp_path, doc))
    node = next(n for n in g.nodes if n.unit_id == "GET /old")
    assert "deprecated" in node.blockers
