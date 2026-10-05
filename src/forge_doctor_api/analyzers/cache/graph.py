"""Spec 063 — cache evidence graph + depth findings.

Edges exist only where *schema-level* evidence links a mutation to a
cached read: both operations must reference the same declared
``#/components/schemas`` component. A shared path prefix alone never
creates an edge — co-location is not evidence of invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from forge_doctor_api.analyzers.cache.model import (
    ApiCacheModel,
    CachePolicy,
)
from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
)
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    Severity,
)

_WRITE_METHODS = {"post", "put", "patch", "delete"}


class CacheEdgeKind(StrEnum):
    INVALIDATES = "invalidates"
    CONFLICTS = "conflicts"


@dataclass(frozen=True, kw_only=True)
class CacheEdge(Model):
    """mutation -> cached-read link via declared schema evidence."""

    from_id: str               # mutating operation id
    to_id: str                 # cached operation/policy subject
    kind: CacheEdgeKind
    via_schema: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CacheGraph(Model):
    cached_operations: tuple[str, ...]
    mutating_operations: tuple[str, ...]
    edges: tuple[CacheEdge, ...]


_SCHEMA_REF = "#/components/schemas/"


def _schemas_of(
    op: OpenApiOperation, known: set[str],
    refs: tuple[Any, ...],
) -> set[str]:
    """Declared schema components referenced under the op's pointer —
    resolved `$ref` records only, never name similarity."""
    out: set[str] = set()
    for r in refs:
        if not (r.pointer == op.pointer
                or r.pointer.startswith(op.pointer + "/")):
            continue
        if not r.ref.startswith(_SCHEMA_REF):
            continue
        name = r.ref[len(_SCHEMA_REF):]
        if name in known:
            out.add(name)
    return out


def _ev(source: str, summary: str) -> Evidence:
    return Evidence(kind=EvidenceKind.STATIC, source=source,
                    summary=summary)


def build_cache_graph(
    model: ApiCacheModel,
    openapi: OpenApiProjectModel,
) -> tuple[CacheGraph, tuple[Finding, ...]]:
    """Graph + stale-window/layer-conflict candidates."""
    known = {s.name for s in openapi.schemas}
    cached: dict[str, CachePolicy] = {}
    writers: dict[str, OpenApiOperation] = {}
    op_schema: dict[str, set[str]] = {}
    for op in openapi.operations:
        op_schema[op.identity] = _schemas_of(op, known, openapi.references)
        if op.method.lower() in _WRITE_METHODS:
            writers[op.identity] = op
    for pol in model.policies:
        cached.setdefault(pol.subject, pol)

    edges: list[CacheEdge] = []
    findings: list[Finding] = []
    writer_subjects: dict[str, list[str]] = {}
    reads = {
        op.identity: op for op in openapi.operations
        if op.method.lower() not in _WRITE_METHODS}
    # policy subject -> covered read operations (declared subject only:
    # identity, or the policy's literal path)
    for subject in cached:
        covered = [
            r for r in reads.values()
            if r.identity == subject or r.path == subject]
        for wid, wop in writers.items():
            for r in covered:
                shared = sorted(
                    op_schema.get(wid, set())
                    & op_schema.get(r.identity, set()))
                if not shared:
                    continue
                edges.append(CacheEdge(
                    from_id=wid, to_id=r.identity,
                    kind=CacheEdgeKind.INVALIDATES,
                    via_schema=shared[0],
                    evidence=(
                        _ev(wop.location.path,
                            f"{wid} mutates schema {shared[0]} served "
                            f"by cached {r.identity}"),)))
                writer_subjects.setdefault(subject, []).append(wid)

    # stale-window candidates: declared ttl + evidenced writer
    for subject, pol in sorted(cached.items()):
        if pol.ttl is None or subject not in writer_subjects:
            continue
        for wid in sorted(set(writer_subjects[subject])):
            wop = writers[wid]
            findings.append(Finding(
                id="APICACHE001",
                title="Stale-window candidate on cached operation",
                description=(
                    f"{subject}: declared ttl={pol.ttl} with evidenced "
                    f"writer {wid} - responses may serve stale data for "
                    f"up to {pol.ttl} after a write"),
                severity=Severity.LOW, confidence=Confidence.LOW,
                evidence_kind=EvidenceKind.CONFIG,
                evidence=(
                    _ev(pol.location.path,
                        f"ttl={pol.ttl} on {subject}"),
                    _ev(wop.location.path,
                        f"writer edge {wid} via schema"),
                ),
            ))

    # APICACHE003 - writer-reader conflict on a shared declared key:
    # two policies bind the same `key` while their subjects split
    # across an evidenced mutating op and an evidenced read op
    # (spec 079). Only declared keys + declared subjects join.
    by_key: dict[str, list[CachePolicy]] = {}
    for pol in model.policies:
        if pol.key:
            by_key.setdefault(pol.key, []).append(pol)

    def _op_names(op: OpenApiOperation) -> set[str]:
        return {op.identity, op.path, f"{op.method.upper()} {op.path}",
                *({op.operation_id} if op.operation_id else ())}

    write_names = {n for wop in writers.values() for n in _op_names(wop)}
    read_names = {n for rop in reads.values() for n in _op_names(rop)}
    for key, pols in sorted(by_key.items()):
        if len(pols) < 2:
            continue
        hits_w = sorted({p.subject for p in pols
                         if p.subject in write_names})
        hits_r = sorted({p.subject for p in pols
                         if p.subject in read_names})
        if not hits_w or not hits_r:
            continue
        findings.append(Finding(
            id="APICACHE003",
            title="Shared cache key across writer/reader subjects",
            description=(
                f"declared key '{key}' spans writer {hits_w} and "
                f"reader {hits_r} - writer-reader invalidation "
                "conflict candidate"),
            severity=Severity.MEDIUM, confidence=Confidence.LOW,
            evidence_kind=EvidenceKind.CONFIG,
            evidence=tuple(
                _ev(p.location.path,
                    f"key='{key}' on {p.subject} ({p.layer.value})")
                for p in pols),
        ))

    # cross-layer conflict candidates
    by_subject: dict[str, list[CachePolicy]] = {}
    for pol in model.policies:
        by_subject.setdefault(pol.subject, []).append(pol)
    for subject, pols in sorted(by_subject.items()):
        stale = {p.stale_policy for p in pols if p.stale_policy}
        layers = {p.layer for p in pols}
        if len(stale) > 1 and len(layers) > 1:
            findings.append(Finding(
                id="APICACHE002",
                title="Conflicting stale policies across cache layers",
                description=(
                    f"{subject}: layers declare conflicting "
                    f"stale_policy values {sorted(stale)}"),
                severity=Severity.MEDIUM, confidence=Confidence.LOW,
                evidence_kind=EvidenceKind.CONFIG,
                evidence=tuple(
                    _ev(p.location.path,
                        f"{p.layer} stale_policy={p.stale_policy}")
                    for p in pols if p.stale_policy),
            ))

    graph = CacheGraph(
        cached_operations=tuple(sorted(cached)),
        mutating_operations=tuple(sorted(writers)),
        edges=tuple(sorted(
            edges, key=lambda e: (e.from_id, e.to_id, e.kind.value))))
    return graph, tuple(findings)
