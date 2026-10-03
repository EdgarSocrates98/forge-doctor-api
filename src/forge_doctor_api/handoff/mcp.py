"""§133 MCP method surface — typed local invocation, no server transport.

Each method returns a serializable payload (Model or plain dict) so a
future transport can carry them unchanged. Nothing here performs network
I/O; the surface is a callable local API over a ProjectContext.
"""

from __future__ import annotations

from typing import Any, cast

from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.model import (
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.runtime.execution import (
    executions_from_traces,
)
from forge_doctor_api.analyzers.runtime.loader import (
    load_runtime_project,
)
from forge_doctor_api.analyzers.runtime.model import (
    ApiObservabilityModel,
    TraceModel,
)
from forge_doctor_api.change.blast import blast_radius
from forge_doctor_api.checks.client.engine import ImpactReport, client_impact
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff, diff_models
from forge_doctor_api.checks.perf.engine import run_perf_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.reliability.model import ApiReliabilityModel
from forge_doctor_api.security.model import ApiSecurityModel
from forge_doctor_api.security.scan import load_security_model


class DoctorApi:
    """§133 typed method surface.

    Methods are pure functions of context contents; models are loaded
    lazily and cached per instance. `before` (when provided) enables the
    diff-based methods (`get_breaking_changes`, `get_blast_radius`).
    """

    def __init__(
        self,
        context: ProjectContext,
        *,
        before: ProjectContext | None = None,
    ) -> None:
        self._ctx = context
        self._before = before
        self._cache: dict[str, Any] = {}

    # -- lazy model access -------------------------------------------------

    def _openapi(self) -> OpenApiProjectModel:
        if "openapi" not in self._cache:
            self._cache["openapi"] = load_openapi_project(self._ctx)
        return cast(OpenApiProjectModel, self._cache["openapi"])

    def _before_openapi(self) -> OpenApiProjectModel | None:
        if self._before is None:
            return None
        if "before_openapi" not in self._cache:
            self._cache["before_openapi"] = load_openapi_project(self._before)
        return cast(OpenApiProjectModel, self._cache["before_openapi"])

    def _files(self) -> list[str]:
        return list(self._ctx.iter_files())

    def _security(self) -> ApiSecurityModel:
        if "security" not in self._cache:
            self._cache["security"] = load_security_model(
                self._ctx, self._files(), openapi=self._openapi())
        return cast(ApiSecurityModel, self._cache["security"])

    def _reliability(self) -> ApiReliabilityModel:
        if "reliability" not in self._cache:
            self._cache["reliability"] = load_reliability_model(
                self._ctx, self._files())
        return cast(ApiReliabilityModel, self._cache["reliability"])

    def _clients(self) -> ApiClientModel:
        if "clients" not in self._cache:
            self._cache["clients"] = scan_clients(self._ctx, self._files())
        return cast(ApiClientModel, self._cache["clients"])

    def _runtime(
        self,
    ) -> tuple[tuple[TraceModel, ...], ApiObservabilityModel,
               tuple[UnknownFact, ...]]:
        if "runtime" not in self._cache:
            self._cache["runtime"] = load_runtime_project(
                self._ctx, self._files(), keep_spans=True)
        return cast(
            tuple[tuple[TraceModel, ...], ApiObservabilityModel,
                  tuple[UnknownFact, ...]],
            self._cache["runtime"])

    def _diff(self) -> ContractDiff | None:
        old = self._before_openapi()
        if old is None:
            return None
        if "diff" not in self._cache:
            self._cache["diff"] = diff_models(old, self._openapi())
        return cast(ContractDiff, self._cache["diff"])

    # -- §133 methods --------------------------------------------------------

    def get_service(self) -> dict[str, Any]:
        """Service-level summary: titles, versions, operation counts."""
        api = self._openapi()
        return {
            "documents": [
                {
                    "path": d.location.path,
                    "openapi_version": d.openapi_version,
                    "title": d.title,
                    "api_version": d.api_version,
                    "status": d.status.value,
                }
                for d in api.documents
            ],
            "operations": sum(
                1 for o in api.operations
                if o.source is OperationSource.PATH),
            "servers": [s.url for s in api.servers],
        }

    def get_api(self) -> dict[str, Any]:
        """Contract surface: methods+paths, never payloads."""
        api = self._openapi()
        return {
            "operations": [
                {
                    "method": o.method, "path": o.path,
                    "operation_id": o.operation_id,
                    "deprecated": o.deprecated, "tags": list(o.tags),
                }
                for o in api.operations
                if o.source is OperationSource.PATH
            ],
        }

    def get_operation(self, operation_id: str) -> dict[str, Any] | None:
        api = self._openapi()
        for o in api.operations:
            if o.operation_id == operation_id or o.identity == operation_id:
                return {
                    "method": o.method, "path": o.path,
                    "operation_id": o.operation_id,
                    "deprecated": o.deprecated,
                    "source": o.source.value,
                    "location": o.location.path,
                }
        return None

    def get_contract(self) -> dict[str, Any]:
        """Contract metadata (doc identity + versions), not raw bodies."""
        api = self._openapi()
        return {
            "schema_version": api.schema_version,
            "documents": [
                {
                    "path": d.location.path, "format": d.format,
                    "status": d.status.value,
                    "openapi_version": d.openapi_version,
                    "family": d.version_family,
                }
                for d in api.documents
            ],
            "schemas": [s.name for s in api.schemas],
        }

    def get_clients(self) -> dict[str, Any]:
        clients = self._clients()
        return {
            "clients": list(clients.clients),
            "call_sites": len(clients.call_sites),
            "unknowns": [u.missing for u in clients.unknowns],
        }

    def get_breaking_changes(self) -> dict[str, Any] | None:
        diff = self._diff()
        if diff is None:
            return None
        return {
            "breaking": [
                {"kind": c.kind, "subject": c.subject, "path": c.path,
                 "detail": c.detail}
                for c in diff.changes
                if c.classification is CompatibilityClass.BREAKING
            ],
            "unknowns": [u.missing for f in diff.findings
                         for u in f.unknowns],
        }

    def get_blast_radius(self) -> dict[str, Any] | None:
        """§68 blast radius over every non-NON_BREAKING change subject."""
        diff = self._diff()
        old = self._before_openapi()
        if diff is None or old is None:
            return None
        return blast_radius(diff, old, self._clients()).to_dict()

    def get_runtime_baseline(self) -> dict[str, Any]:
        _, observability, unknowns = self._runtime()
        data = observability.to_dict()
        data["unknowns"] = [
            {"subject": u.subject, "missing": u.missing}
            for u in unknowns
        ]
        return data

    def get_regressions(self) -> dict[str, Any]:
        traces, _, rt_unknowns = self._runtime()
        executions, exec_unknowns = executions_from_traces(traces)
        findings = run_perf_checks(executions)
        return {
            "findings": [f.to_dict() for f in findings],
            "unknowns": [
                {"subject": u.subject, "missing": u.missing}
                for u in (*rt_unknowns, *exec_unknowns)
            ],
        }

    def get_security_findings(self) -> dict[str, Any]:
        return self._security().to_dict()

    def get_reliability_status(self) -> dict[str, Any]:
        rel = self._reliability()
        return {
            "retry_policies": len(rel.retry_policies),
            "timeouts": len(rel.timeouts),
            "circuit_breakers": len(rel.circuit_breakers),
            "health_checks": len(rel.health_checks),
            "idempotency": [
                {"subject": i.subject, "verdict": i.verdict.value}
                for i in rel.idempotency
            ],
            "unknowns": [u.missing for u in rel.unknowns],
        }

    def get_unknowns(self) -> dict[str, Any]:
        unknowns: list[dict[str, str]] = []
        for model in (self._security(), self._reliability(),
                      self._clients()):
            unknowns.extend(
                {"subject": u.subject, "missing": u.missing,
                 "resolution": u.resolution}
                for u in model.unknowns
            )
        unknowns.extend(
            {"subject": r.ref, "missing": "external reference unresolved",
             "resolution": "provide the referenced document"}
            for r in self._openapi().unresolved_external_refs
        )
        return {"unknowns": unknowns}

    # -- client impact convenience (needs the diff) -------------------------

    def impact_report(self) -> ImpactReport | None:
        diff = self._diff()
        old = self._before_openapi()
        if diff is None or old is None:
            return None
        return client_impact(diff, self._clients(), old)
