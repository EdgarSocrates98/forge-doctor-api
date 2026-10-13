"""Spec 066 — analysis stats + check-description lookup.

Stats are deterministic counts (which analyzers ran, how many
artifacts each consumed, how many findings/unknowns each emitted).
`duration_ms` is the only wall-time field: it stays ``None`` unless
the caller opts into ``stats_timing`` — deterministic output is the
default and timing never enters the canonical surface uninvited.

`describe_check` resolves a check id to its catalog spec (the rule's
documented severity/confidence/description) across every shipped
catalog — explain surfaces quote the rule, not just the finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_doctor_api.core.models import Model


@dataclass(frozen=True, kw_only=True)
class AnalyzerStat(Model):
    """One analyzer's observed work in a scan."""

    analyzer: str
    ran: bool
    artifacts: int = 0
    findings: int = 0
    unknowns: int = 0
    duration_ms: float | None = None  # only with stats_timing
    allocated_bytes: int | None = None  # only with stats_timing+tracemalloc


@dataclass(frozen=True, kw_only=True)
class AnalysisStats(Model):
    """Deterministic per-analyzer counters + totals (spec 066)."""

    analyzers: tuple[AnalyzerStat, ...]
    total_findings: int = 0
    total_unknowns: int = 0


# -- catalog lookup -----------------------------------------------------------

_CATALOG_MODULES = (
    "oas", "apisec", "relapi", "client", "compat", "drift",
    "graphql", "grpc", "observability", "perf", "asyncapi",
)

_catalog_cache: dict[str, Any] | None = None


def _catalog() -> dict[str, Any]:
    global _catalog_cache
    if _catalog_cache is None:
        import importlib
        found: dict[str, Any] = {}
        for mod in _CATALOG_MODULES:
            try:
                module = importlib.import_module(
                    f"forge_doctor_api.checks.{mod}.catalog")
            except ImportError:
                continue
            for cid, spec in getattr(module, "BY_ID", {}).items():
                found.setdefault(cid, spec)
        _catalog_cache = found
    return _catalog_cache


def describe_check(check_id: str) -> Any | None:
    """Catalog spec for `check_id` (title/severity/confidence/
    description) or None for ids outside the shipped catalogs."""
    return _catalog().get(check_id)


def rule_text(spec: Any) -> str:
    """Normalized rule description across heterogeneous catalogs —
    some ship `description`, others `trigger`."""
    return str(getattr(spec, "description",
                       getattr(spec, "trigger", "")))


def rule_dict(spec: Any) -> dict[str, Any]:
    """Stable JSON-safe projection of a catalog spec."""
    return {
        "id": getattr(spec, "id", ""),
        "title": getattr(spec, "title", ""),
        "severity": getattr(getattr(spec, "severity", None),
                           "value", getattr(spec, "severity", None)),
        "confidence": getattr(getattr(spec, "confidence", None),
                             "value", getattr(spec, "confidence", None)),
        "description": rule_text(spec),
    }
