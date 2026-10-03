"""Twin assembly (§63) - project existing models into five states.

Each `TwinStateView` is a compact projection: record count + a
deterministic fingerprint + key identifiers + the evidence sources it
was built from. Sources are never duplicated; callers keep the source
models.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.routes.model import RouteScan
from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    UnknownFact,
)
from forge_doctor_api.perf.experiments import Experiment
from forge_doctor_api.reliability.model import ApiReliabilityModel
from forge_doctor_api.security.model import ApiSecurityModel
from forge_doctor_api.twin.model import (
    ApiDigitalTwin,
    TwinState,
    TwinStateView,
)


def _fp(items: Any) -> str:
    """Deterministic short fingerprint of canonical items."""
    blob = json.dumps(items, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _desired_view(
    reliability: ApiReliabilityModel | None,
) -> TwinStateView:
    """DESIRED: objectives, platform policy + business-flow records."""
    if reliability is None:
        return TwinStateView(
            state=TwinState.DESIRED,
            present=False,
            unknowns=(
                UnknownFact(
                    subject="DESIRED state",
                    missing="SLOs / platform policies / business flows",
                    resolution="provide declared objectives or "
                    "policy config",
                ),
            ),
        )
    objectives = reliability.objectives
    identifiers = tuple(sorted(o.name for o in objectives))
    srcs = tuple(
        sorted({e.source for o in objectives for e in o.evidence})
    )
    return TwinStateView(
        state=TwinState.DESIRED,
        present=bool(identifiers),
        record_count=len(identifiers),
        fingerprint=_fp(
            [(o.name, o.metric, o.target, o.window) for o in objectives]
        ),
        identifiers=identifiers,
        sources=srcs,
        evidence=tuple(e for o in objectives for e in o.evidence)[:8],
        unknowns=(
            ()
            if identifiers
            else (
                UnknownFact(
                    subject="DESIRED state",
                    missing="SLOs / platform policies / business flows",
                    resolution="provide declared objectives or "
                    "policy config",
                ),
            )
        ),
    )


def _declared_view(
    openapi: OpenApiProjectModel | None,
    reliability: ApiReliabilityModel | None,
) -> TwinStateView:
    """DECLARED: contract artifacts + gateway/reliability config."""
    ids: list[str] = []
    sources: set[str] = set()
    if openapi is not None:
        ids.extend(op.identity for op in openapi.operations)
        ids.extend(f"schema:{s.name}" for s in openapi.schemas)
        for doc in openapi.documents:
            sources.add(doc.location.path)
    if reliability is not None:
        ids.extend(f"retry:{r.scope}" for r in reliability.retry_policies)
        ids.extend(f"timeout:{t.scope}" for t in reliability.timeouts)
        for group in (
            reliability.retry_policies,
            reliability.timeouts,
            reliability.circuit_breakers,
        ):
            for item in group:
                for e in item.evidence:
                    sources.add(e.source)
    ids = sorted(set(ids))
    return TwinStateView(
        state=TwinState.DECLARED,
        present=bool(ids),
        record_count=len(ids),
        fingerprint=_fp(ids) if ids else None,
        identifiers=tuple(ids),
        sources=tuple(sorted(sources)),
        unknowns=(
            ()
            if ids
            else (
                UnknownFact(
                    subject="DECLARED state",
                    missing="OpenAPI/AsyncAPI/gateway config artifacts",
                    resolution="provide contract or config files",
                ),
            )
        ),
    )


def _implemented_view(routes: RouteScan | None) -> TwinStateView:
    """IMPLEMENTED: source routes, handlers, clients."""
    if routes is None or not routes.routes:
        return TwinStateView(
            state=TwinState.IMPLEMENTED,
            present=False,
            unknowns=(
                UnknownFact(
                    subject="IMPLEMENTED state",
                    missing="framework routes/handlers",
                    resolution="scan source with a framework adapter",
                ),
            ),
        )
    ids = sorted(
        f"{r.method.upper()} {r.path} -> {r.handler}"
        for r in routes.routes
    )
    return TwinStateView(
        state=TwinState.IMPLEMENTED,
        present=True,
        record_count=len(ids),
        fingerprint=_fp(ids),
        identifiers=tuple(ids),
        sources=tuple(sorted({r.source_location.path
                              for r in routes.routes})),
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source="(routes)",
                summary=f"{len(routes.routes)} routes in "
                f"{routes.service}",
            ),
        ),
    )


def _observed_view(
    executions: tuple[RequestExecution, ...] | None,
) -> TwinStateView:
    """OBSERVED: normalized request executions (summary level)."""
    if not executions:
        return TwinStateView(
            state=TwinState.OBSERVED,
            present=False,
            unknowns=(
                UnknownFact(
                    subject="OBSERVED state",
                    missing="traces/access logs/runtime metadata",
                    resolution="export runtime artifacts (OTLP JSON, "
                    "access logs) into the project",
                ),
            ),
        )
    ops = sorted({f"{e.service}:{e.operation}" for e in executions})
    return TwinStateView(
        state=TwinState.OBSERVED,
        present=True,
        record_count=len(executions),
        fingerprint=_fp(
            [
                (e.request_id, e.operation, e.duration_ms, e.status)
                for e in executions
            ]
        ),
        identifiers=tuple(ops[:64]),
        sources=tuple(sorted(
            {ev.source for e in executions for ev in e.evidence}
        )),
        unknowns=(),
    )


def _hypothetical_view(
    experiments: tuple[Experiment, ...] | None,
    labels: tuple[str, ...] = (),
) -> TwinStateView:
    """HYPOTHETICAL: experiments/migration scenarios - isolated view."""
    names = tuple(
        sorted({*(e.name for e in experiments or ()), *labels})
    )
    return TwinStateView(
        state=TwinState.HYPOTHETICAL,
        present=bool(names),
        record_count=len(names),
        fingerprint=_fp(list(names)) if names else None,
        identifiers=names,
        unknowns=(
            ()
            if names
            else (
                UnknownFact(
                    subject="HYPOTHETICAL state",
                    missing="experiment/migration scenarios",
                    resolution="attach a what-if scenario to populate "
                    "this state",
                ),
            )
        ),
    )


def assemble_twin(
    openapi: OpenApiProjectModel | None = None,
    routes: RouteScan | None = None,
    reliability: ApiReliabilityModel | None = None,
    executions: tuple[RequestExecution, ...] | None = None,
    security: ApiSecurityModel | None = None,
    experiments: tuple[Experiment, ...] | None = None,
    hypothesis_labels: tuple[str, ...] = (),
) -> ApiDigitalTwin:
    """Assemble the §63 five-state twin from existing model outputs.

    Missing inputs -> absent views with `UnknownFact`s; states never
    borrow each other's confidence.
    """
    del security  # security evidence flows via drift, not a state view
    states = (
        _desired_view(reliability),
        _declared_view(openapi, reliability),
        _implemented_view(routes),
        _observed_view(executions),
        _hypothetical_view(experiments, hypothesis_labels),
    )
    missing = [v.state.value for v in states if not v.present]
    return ApiDigitalTwin(
        states=states,
        unknowns=tuple(
            UnknownFact(
                subject=f"{s} state",
                missing="source evidence for this plane",
                resolution="provide the corresponding artifacts",
            )
            for s in missing
        ),
    )
