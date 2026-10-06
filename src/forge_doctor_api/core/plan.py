"""AnalysisPlan — evidence-driven analyzer selection (§12).

`build_plan` decides which analyzers apply from the classified
inventory — `.proto` -> grpc, graphql markers -> graphql, runtime
artifacts -> runtime, terraform/k8s -> iac, gateway markers -> gateway.
An analyzer runs only when at least one of its required classes or
markers is present; `force=True` returns every analyzer (parity/testing).

The plan is data, not execution: `scan_project` consumes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.discovery import (
    ArtifactClass,
    ArtifactInventory,
)
from forge_doctor_api.core.models import Model


class AnalyzerId(StrEnum):
    """Stable analyzer identifiers used by plans and stats."""

    OPENAPI = "openapi"
    ASYNCAPI = "asyncapi"
    GRAPHQL = "graphql"
    GRPC = "grpc"
    ROUTES = "routes"
    CLIENTS = "clients"
    RUNTIME = "runtime"
    GATEWAY = "gateway"
    IAC = "iac"
    CACHE = "cache"
    SECURITY = "security"
    RELIABILITY = "reliability"
    POLICY = "policy"
    VERSION = "version"
    WORKSPACE = "workspace"
    OWNERSHIP = "ownership"
    DOCUMENTATION = "documentation"


@dataclass(frozen=True, kw_only=True)
class AnalyzerRequirement(Model):
    """Enable rule: any matching class OR any matching marker."""

    analyzer: AnalyzerId
    any_classes: tuple[ArtifactClass, ...] = ()
    any_markers: tuple[str, ...] = ()


# Registry — permissive enabling; the analyzer's own detection is
# authoritative. Ordered: plan output order = registry order.
ANALYZER_REQUIREMENTS: tuple[AnalyzerRequirement, ...] = (
    AnalyzerRequirement(
        analyzer=AnalyzerId.OPENAPI,
        any_markers=("openapi", "swagger"),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.ASYNCAPI,
        any_markers=("asyncapi",),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.GRAPHQL,
        any_markers=("graphql",),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.GRPC,
        any_markers=("proto",),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.ROUTES,
        any_classes=(ArtifactClass.SOURCE,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.CLIENTS,
        any_classes=(ArtifactClass.CLIENT,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.RUNTIME,
        any_classes=(ArtifactClass.RUNTIME,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.GATEWAY,
        any_classes=(ArtifactClass.GATEWAY, ArtifactClass.MESH),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.IAC,
        any_classes=(ArtifactClass.IAC,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.CACHE,
        any_classes=(ArtifactClass.CONFIG,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.SECURITY,
        any_classes=(
            ArtifactClass.SOURCE,
            ArtifactClass.CONFIG,
            ArtifactClass.CONTRACT,
        ),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.RELIABILITY,
        any_classes=(ArtifactClass.CONFIG, ArtifactClass.SOURCE),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.POLICY,
        any_classes=(ArtifactClass.POLICY,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.VERSION,
        any_classes=(ArtifactClass.CONTRACT,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.WORKSPACE,
        any_classes=(ArtifactClass.WORKSPACE,),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.OWNERSHIP,
        any_classes=(
            ArtifactClass.OWNERSHIP,
            ArtifactClass.CONFIG,
            ArtifactClass.CONTRACT,
        ),
    ),
    AnalyzerRequirement(
        analyzer=AnalyzerId.DOCUMENTATION,
        any_classes=(ArtifactClass.DOCUMENTATION,),
    ),
)


@dataclass(frozen=True, kw_only=True)
class SkippedAnalyzer(Model):
    analyzer: AnalyzerId
    reason: str


@dataclass(frozen=True, kw_only=True)
class AnalysisPlan(Model):
    """Which analyzers apply, and why — deterministic (§12)."""

    analyzers: tuple[AnalyzerId, ...] = ()
    reasons: tuple[tuple[str, str], ...] = ()  # analyzer -> evidence basis
    skipped: tuple[SkippedAnalyzer, ...] = ()

    def enabled(self, analyzer: AnalyzerId) -> bool:
        return analyzer in self.analyzers


def build_plan(inventory: ArtifactInventory, *, force: bool = False) -> AnalysisPlan:
    """Plan from the classified inventory — evidence, never guesses."""
    analyzers: list[AnalyzerId] = []
    reasons: list[tuple[str, str]] = []
    skipped: list[SkippedAnalyzer] = []
    present_markers = inventory.markers()
    for req in ANALYZER_REQUIREMENTS:
        matched_classes = [
            c for c in req.any_classes if inventory.has_class(c)
        ]
        matched_markers = [m for m in req.any_markers if m in present_markers]
        if force or matched_classes or matched_markers:
            analyzers.append(req.analyzer)
            if matched_classes:
                basis = "class:" + ",".join(c.value for c in matched_classes)
            elif matched_markers:
                basis = "marker:" + ",".join(sorted(matched_markers))
            else:
                basis = "forced"
            reasons.append((req.analyzer.value, basis))
        else:
            skipped.append(
                SkippedAnalyzer(
                    analyzer=req.analyzer,
                    reason="no evidence",
                )
            )
    return AnalysisPlan(
        analyzers=tuple(analyzers),
        reasons=tuple(reasons),
        skipped=tuple(skipped),
    )
