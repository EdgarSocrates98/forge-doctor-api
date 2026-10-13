"""GQL001-GQL010 check engine (§23).

Single-model checks (001, 006-010) run on a `GraphQLProjectModel`.
Diff checks (002-005) run via `graphql_breaking_changes`, which classifies
through `diff_graphql_schemas` using unified compat classes (§121-123).

Static-runtime boundary (§102): GQL006-010 emit LOW-confidence candidates
with UnknownFacts - never violations asserted from static shape alone.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.graphql.compat import diff_graphql_schemas
from forge_doctor_api.analyzers.graphql.model import (
    GraphQLProjectModel,
    GraphQLTypeKind,
)
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.graphql.catalog import BY_ID, GqlCheckSpec
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    SourceLocation,
    UnknownFact,
    entity_id,
)

_PAGINATION = {"first", "last", "after", "before", "limit", "offset", "page", "pageSize"}
_DEPTH_THRESHOLD = 5
_SCALAR_KINDS = {GraphQLTypeKind.SCALAR, GraphQLTypeKind.ENUM}


def _finding(
    spec: GqlCheckSpec,
    description: str,
    location: SourceLocation,
    *,
    entities: tuple[str, ...] = (),
    unknowns: tuple[UnknownFact, ...] = (),
    summary: str | None = None,
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=location.path,
                summary=summary or description,
                line=location.line,
            ),
        ),
        entity_ids=entities,
        source_location=location,
        unknowns=unknowns,
    )


def run_graphql_checks(model: GraphQLProjectModel) -> tuple[Finding, ...]:
    """Single-schema GQL checks (GQL001, GQL006-GQL010)."""
    findings: list[Finding] = []

    # -- GQL001 deprecated field with active clients --------------------------
    touched = {t for q in model.client_queries for t in q.fields_touched}
    for t in model.types:
        for f in t.fields:
            if f.deprecated and f"{t.name}.{f.name}" in touched:
                findings.append(
                    _finding(
                        BY_ID["GQL001"],
                        f"deprecated field {t.name}.{f.name} still selected by a "
                        f"client query (reason: {f.deprecation_reason or 'n/a'})",
                        f.location,
                        entities=(
                            entity_id("graphql_type", "graphql", f"{t.kind}:{t.name}"),
                        ),
                    )
                )

    # -- GQL006 resolver without authorization evidence -----------------------
    lacking = [r for r in model.resolvers if not r.auth_evidence]
    if lacking:
        names = ", ".join(f"{r.type_name}.{r.field_name}" for r in lacking[:10])
        more = f" (+{len(lacking) - 10} more)" if len(lacking) > 10 else ""
        findings.append(
            _finding(
                BY_ID["GQL006"],
                f"{len(lacking)} resolver(s) without authorization directive "
                f"evidence: {names}{more}",
                lacking[0].location,
                unknowns=(
                    UnknownFact(
                        subject="resolver authorization",
                        missing="code-level or middleware auth enforcement evidence",
                        resolution="inspect resolver implementations or attach auth "
                        "directives",
                    ),
                ),
            )
        )

    # -- GQL007 unbounded list field ------------------------------------------
    for t in model.types:
        if t.kind not in {GraphQLTypeKind.OBJECT, GraphQLTypeKind.INTERFACE}:
            continue
        for f in t.fields:
            if not f.type.is_list:
                continue
            if {a.name for a in f.arguments} & _PAGINATION:
                continue
            findings.append(
                _finding(
                    BY_ID["GQL007"],
                    f"list field {t.name}.{f.name} has no pagination arguments",
                    f.location,
                    entities=(
                        entity_id("graphql_type", "graphql", f"{t.kind}:{t.name}"),
                    ),
                    unknowns=(
                        UnknownFact(
                            subject=f"{t.name}.{f.name}",
                            missing="server-side result-set cap evidence",
                            resolution="runtime cardinality evidence or pagination "
                            "arguments",
                        ),
                    ),
                )
            )

    # -- GQL008 deep traversal candidate --------------------------------------
    for cycle in _type_cycles(model):
        head = model.type_named(cycle[0])
        findings.append(
            _finding(
                BY_ID["GQL008"],
                f"recursive type path admits unbounded query depth: "
                f"{' -> '.join(cycle)}",
                head.location if head is not None else SourceLocation(path="(schema)"),
                unknowns=(
                    UnknownFact(
                        subject="query depth",
                        missing="a documented depth-limit policy or runtime depth "
                        "evidence",
                        resolution="confirm a depth limiter exists or cap traversal",
                    ),
                ),
            )
        )
    for q in model.client_queries:
        if q.shape.depth > _DEPTH_THRESHOLD:
            findings.append(
                _finding(
                    BY_ID["GQL008"],
                    f"client query '{q.operation or '(anonymous)'}' depth "
                    f"{q.shape.depth} exceeds {_DEPTH_THRESHOLD}",
                    q.location,
                )
            )

    # -- GQL009 N+1 candidate ---------------------------------------------------
    type_kinds = {t.name: t.kind for t in model.types}
    has_nested = {
        t.name
        for t in model.types
        if any(type_kinds.get(f.type.name) not in _SCALAR_KINDS for f in t.fields)
    }
    for t in model.types:
        if t.kind not in {GraphQLTypeKind.OBJECT, GraphQLTypeKind.INTERFACE}:
            continue
        for f in t.fields:
            if f.type.is_list and f.type.name in has_nested:
                findings.append(
                    _finding(
                        BY_ID["GQL009"],
                        f"list field {t.name}.{f.name} returns objects with "
                        f"sub-object fields - N+1 static candidate",
                        f.location,
                        unknowns=(
                            UnknownFact(
                                subject=f"{t.name}.{f.name}",
                                missing="runtime resolver invocation counts",
                                resolution="RUNTIME trace evidence confirms or "
                                "clears the N+1 (§102)",
                            ),
                        ),
                    )
                )

    # -- GQL010 introspection exposure ------------------------------------------
    if model.introspection:
        for ev in model.introspection:
            if ev.enabled:
                findings.append(
                    _finding(
                        BY_ID["GQL010"],
                        f"introspection enabled by config evidence: {ev.detail}",
                        ev.location,
                        unknowns=(
                            UnknownFact(
                                subject="introspection policy",
                                missing="a declared introspection policy to compare "
                                "against",
                                resolution="declare policy in org config (spec 023)",
                            ),
                        ),
                    )
                )
    else:
        first = model.types[0].location if model.types else None
        findings.append(
            _finding(
                BY_ID["GQL010"],
                "no introspection policy evidence found - exposure undetermined",
                first or SourceLocation(path="(workspace)"),
                unknowns=(
                    UnknownFact(
                        subject="introspection exposure",
                        missing="config evidence of introspection enabled/disabled",
                        resolution="provide server config declaring introspection",
                    ),
                ),
            )
        )
    return tuple(findings)


def _type_cycles(model: GraphQLProjectModel) -> list[tuple[str, ...]]:
    """Iterative DFS detecting cycles in the named-type graph (capped at 64).

    Self-referencing types (``Employee.manager: Employee``) count - they
    admit arbitrary-depth traversal just like A->B->A cycles.
    """
    edges: dict[str, set[str]] = {}
    known = {t.name for t in model.types}
    for t in model.types:
        if t.kind is GraphQLTypeKind.SCALAR:
            continue
        targets = {f.type.name for f in t.fields if f.type.name in known}
        targets |= {m for m in t.union_members if m in known}
        edges[t.name] = targets

    cycles: list[tuple[str, ...]] = []
    seen_cycles: set[frozenset[str]] = set()
    for start in sorted(edges):
        if len(cycles) >= 64:
            break
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            node, path = stack.pop()
            for nxt in sorted(edges.get(node, set())):
                if nxt in path:
                    cycle = path[path.index(nxt):]
                    key = frozenset(cycle)
                    if key not in seen_cycles and len(cycles) < 64:
                        seen_cycles.add(key)
                        cycles.append((*tuple(cycle), nxt))
                else:
                    stack.append((nxt, [*path, nxt]))
    return cycles


def graphql_breaking_changes(
    old: GraphQLProjectModel, new: GraphQLProjectModel
) -> tuple[Finding, ...]:
    """Schema diff -> GQL002-005 findings via unified compat classes."""
    findings: list[Finding] = []
    for change in diff_graphql_schemas(old, new):
        spec = BY_ID[change.kind]
        confidence = (
            Confidence.UNKNOWN
            if change.classification is CompatibilityClass.UNKNOWN
            else spec.confidence
        )
        findings.append(
            Finding(
                id=spec.id,
                title=spec.title,
                description=change.detail,
                severity=spec.severity,
                confidence=confidence,
                evidence_kind=spec.evidence_kind,
                evidence=(
                    Evidence(
                        kind=EvidenceKind.STATIC,
                        source=change.location.path if change.location else "(schema)",
                        summary=change.detail,
                        line=change.location.line if change.location else None,
                    ),
                ),
                entity_ids=(change.subject,),
                source_location=change.location,
            )
        )
    return tuple(findings)
