"""RuntimeArtifactAdapter contract (§30, §192 discipline, §171, §173).

Adapters stream offline export files and normalize them to `Span` /
`RequestSummary` records. Detection requires strong format markers —
weak filename/content hints never attribute a format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import BinaryIO

from forge_doctor_api.analyzers.runtime.model import RequestSummary, Span


class RuntimeArtifactAdapter(ABC):
    """One offline runtime-export format (OTLP, access logs, ...)."""

    name: str

    @abstractmethod
    def detect(self, path: str, head: bytes) -> bool:
        """Strong-marker format gate on the first bytes of the artifact."""

    def iter_spans(self, reader: BinaryIO, path: str) -> Iterator[Span]:
        """Stream normalized spans without loading the artifact fully."""
        return iter(())

    def iter_summaries(self, reader: BinaryIO, path: str) -> Iterator[RequestSummary]:
        """Request summaries, where the format has any."""
        return iter(())
