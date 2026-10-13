"""Shared ServiceGraph builder — contract + implementation + client evidence.

Extracted from the ``graph`` command so both the CLI surface and the
ForgeGraphView adapter build the same graph.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.clients.graph import client_graph
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.graph import GraphError, ServiceGraph


def merge_graph(target: ServiceGraph, other: ServiceGraph) -> None:
    for entity in other.entities():
        try:
            target.add_entity(entity)
        except GraphError:
            continue
    for rel in other.relationships():
        try:
            target.add_relationship(rel)
        except GraphError:
            continue


def build_service_graph(path: Path) -> ServiceGraph:
    """The real §161 graph for a target directory."""
    ctx = ProjectContext.from_root(path)
    files = list(ctx.iter_files())
    openapi = load_openapi_project(ctx)
    service_graph = contract_graph(openapi)
    try:
        scan = FastApiAdapter().scan(ctx, path.name)
    except Exception:
        scan = None
    if scan is not None:
        merge_graph(service_graph, scan_graph(scan))
    client_model = scan_clients(ctx, files)
    merge_graph(service_graph, client_graph(client_model))
    return service_graph
