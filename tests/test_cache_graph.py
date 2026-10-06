"""Spec 063 — cache evidence graph: schema-linked invalidation edges,
stale-window candidates, cross-layer conflicts."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.cache.graph import (
    CacheEdgeKind,
    build_cache_graph,
)
from forge_doctor_api.analyzers.cache.model import (
    ApiCacheModel,
    CacheLayer,
    CachePolicy,
)
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation

LOC = SourceLocation(path="cache.yaml", line=1, column=1)


def _policy(subject: str, *, layer: CacheLayer = CacheLayer.GATEWAY,
            ttl: str | None = None,
            stale: str | None = None) -> CachePolicy:
    return CachePolicy(
        subject=subject, layer=layer, ttl=ttl, stale_policy=stale,
        location=LOC)


def _openapi(tmp_path: Path) -> object:
    (tmp_path / "o.yaml").write_text("""
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
    put:
      operationId: updatePet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Pet'}
      responses: {'200': {description: ok}}
  /cars:
    get: {operationId: listCars, responses: {'200': {description: ok}}}
components:
  schemas:
    Pet: {type: object}
""", "utf-8")
    return load_openapi_project(ProjectContext.from_root(tmp_path))


def test_schema_evidence_creates_invalidation_edge(tmp_path: Path) -> None:
    openapi = _openapi(tmp_path)
    subject = next(o.identity for o in openapi.operations
                   if o.operation_id == "listPets")
    model = ApiCacheModel(policies=(_policy(subject, ttl="60s"),))
    graph, findings = build_cache_graph(model, openapi)
    inv = [e for e in graph.edges
           if e.kind is CacheEdgeKind.INVALIDATES]
    assert len(inv) == 1
    assert inv[0].via_schema == "Pet"
    assert inv[0].evidence
    # declared ttl + evidenced writer -> stale-window candidate
    assert any(f.id == "APICACHE001" for f in findings)


def test_no_schema_link_no_edge(tmp_path: Path) -> None:
    openapi = _openapi(tmp_path)
    subject = next(o.identity for o in openapi.operations
                   if o.operation_id == "listCars")
    model = ApiCacheModel(policies=(_policy(subject, ttl="60s"),))
    graph, findings = build_cache_graph(model, openapi)
    assert graph.edges == ()
    assert findings == ()


def test_prefix_only_match_no_edge(tmp_path: Path) -> None:
    """A cached path sharing a prefix with a writer path never edges."""
    openapi = _openapi(tmp_path)
    model = ApiCacheModel(policies=(_policy("/pets", ttl="10s"),))
    graph, _ = build_cache_graph(model, openapi)
    # /pets covers the GET read op; PUT shares the schema -> edge IS
    # legitimate. Prefix-only means: a policy on /petsXYZ must not
    # attach to /pets.
    assert graph.edges, "declared-subject policy links the shared schema"
    model2 = ApiCacheModel(policies=(_policy("/petsXYZ", ttl="10s"),))
    graph2, _ = build_cache_graph(model2, openapi)
    assert graph2.edges == ()


def test_cross_layer_conflict_candidate(tmp_path: Path) -> None:
    openapi = _openapi(tmp_path)
    subject = next(o.identity for o in openapi.operations
                   if o.operation_id == "listPets")
    model = ApiCacheModel(policies=(
        _policy(subject, layer=CacheLayer.GATEWAY, stale="serve-stale"),
        _policy(subject, layer=CacheLayer.SERVICE, stale="reject-stale"),
    ))
    _, findings = build_cache_graph(model, openapi)
    assert any(f.id == "APICACHE002" for f in findings)
    f = next(f for f in findings if f.id == "APICACHE002")
    assert len(f.evidence) == 2


def test_no_ttl_no_stale_candidate(tmp_path: Path) -> None:
    openapi = _openapi(tmp_path)
    subject = next(o.identity for o in openapi.operations
                   if o.operation_id == "listPets")
    model = ApiCacheModel(policies=(_policy(subject),))
    _, findings = build_cache_graph(model, openapi)
    assert not any(f.id == "APICACHE001" for f in findings)


def test_deterministic(tmp_path: Path) -> None:
    openapi = _openapi(tmp_path)
    subject = next(o.identity for o in openapi.operations
                   if o.operation_id == "listPets")
    model = ApiCacheModel(policies=(_policy(subject, ttl="60s"),))
    a = build_cache_graph(model, openapi)
    b = build_cache_graph(model, openapi)
    assert a == b
