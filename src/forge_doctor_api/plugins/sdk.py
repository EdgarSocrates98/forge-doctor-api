"""§131 Plugin SDK — typed protocol surfaces.

These are the contracts an adapter must satisfy. Defining a Protocol is
not loading: conformance is structural and nothing here imports plugin
code (§132 trust boundary lives in `trust.py`).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, BinaryIO, Protocol, runtime_checkable

from forge_doctor_api.core.context import ProjectContext

if TYPE_CHECKING:
    from forge_doctor_api.analyzers.routes.model import RouteScan
    from forge_doctor_api.analyzers.runtime.model import (
        RequestSummary,
        Span,
    )
    from forge_doctor_api.checks.apisec.catalog import SecCheckSpec
    from forge_doctor_api.core.models import Model


@runtime_checkable
class FrameworkAdapter(Protocol):
    """§131 source-framework route/handler extractor (e.g. FastAPI)."""

    name: str

    def scan(
        self,
        context: ProjectContext,
        service: str,
        paths: Sequence[str] | None = None,
    ) -> RouteScan:
        """Attribute files by strong markers; extract route surfaces."""
        ...


@runtime_checkable
class GatewayAdapter(Protocol):
    """§131 gateway config evidence -> declared routes."""

    name: str

    def routes(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Model, ...]:
        """Declarative gateway routes from config evidence."""
        ...


@runtime_checkable
class ContractAdapter(Protocol):
    """§131 contract-format loader (OpenAPI, AsyncAPI, ...)."""

    name: str

    def load(
        self, context: ProjectContext, paths: Sequence[str] | None = None
    ) -> Model:
        """Parse contract documents into the domain model."""
        ...


@runtime_checkable
class RuntimeAdapter(Protocol):
    """§131 runtime artifact format (OTLP, access logs, ...)."""

    name: str

    def detect(self, path: str, head: bytes) -> bool:
        """Strong-marker format gate on the artifact's first bytes."""
        ...

    def iter_spans(self, reader: BinaryIO, path: str) -> Iterator[Span]:
        """Stream normalized spans without loading the artifact fully."""
        ...

    def iter_summaries(
        self, reader: BinaryIO, path: str
    ) -> Iterator[RequestSummary]:
        """Request summaries, where the format has any."""
        ...


@runtime_checkable
class SecurityRulePack(Protocol):
    """§131 extra check specs contributed by a plugin."""

    name: str

    def check_specs(self) -> tuple[SecCheckSpec, ...]:
        """Checks the pack contributes to the security engine."""
        ...
