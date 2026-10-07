"""§76 graph linkage — manifest resources → scanned service identities.

A `DEPLOYED_AS` edge is emitted only when a manifest name is byte-equal
to a scanned service identifier (`service:<domain>:<name>`). No fuzzy
matching: unmatched resources stay unlinked.
"""

from __future__ import annotations

from collections.abc import Iterable

from forge_doctor_api.analyzers.iac.model import InfraModel, K8sKind
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceKind,
    Relationship,
    RelationshipKind,
    entity_id,
    parse_entity_id,
)


def _identifier(service_id: str) -> str | None:
    try:
        _, _, identifier = parse_entity_id(service_id)
    except Exception:
        return None
    return identifier


def infra_graph(
    infra: InfraModel,
    service_ids: Iterable[str] = (),
) -> tuple[tuple[Entity, ...], tuple[Relationship, ...]]:
    """Entities + DEPLOYED_AS edges for manifests matching services."""
    wanted = {
        ident: sid for sid in service_ids
        if (ident := _identifier(sid)) is not None}
    entities: list[Entity] = []
    edges: list[Relationship] = []
    for res in infra.kubernetes:
        if res.kind not in (K8sKind.DEPLOYMENT, K8sKind.SERVICE):
            continue
        target = wanted.get(res.name)
        if target is None:
            continue
        did = entity_id(
            EntityKind.DEPLOYMENT, "k8s",
            f"{res.namespace}.{res.name}" if res.namespace else res.name)
        entities.append(Entity(
            id=did, kind=EntityKind.DEPLOYMENT, name=res.name,
            attributes={"k8s_kind": res.kind.value}))
        edges.append(Relationship(
            kind=RelationshipKind.DEPLOYED_AS,
            source_id=did, target_id=target,
            confidence=Confidence.HIGH,
            evidence=(Evidence(
                kind=EvidenceKind.CONFIG, source=res.location.path,
                line=res.location.line,
                summary=f"{res.kind.value}/{res.name} declares "
                        f"service identity"),)))
    return tuple(entities), tuple(edges)
