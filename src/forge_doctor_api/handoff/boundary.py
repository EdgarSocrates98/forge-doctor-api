"""Spec 070 — The-Forger / API Forge boundary.

`DoctorBoundary` is the only typed exchange point between the Doctor
and its consumers:

```text
ForgeRequest ──▶ DoctorBoundary ──▶ ForgeHandoff ──▶ (consumer)
                                        │
                                   ForgeReceipt ◀── (consumer)
```

What the Doctor owns (and only this): **observe, normalize, detect,
measure, diagnose, classify, impact, report unknowns, serve context.**

Non-goals, enforced structurally — this module contains no method
that:

- routes work to another component (routing is The Forger's),
- schedules or retries anything,
- implements, edits or generates code in the target repo
  (implementation is API Forge's),
- calls out: no network, no subprocess, no dynamic import, no
  target-code execution. The purity test in
  `tests/test_boundary.py` enforces this at the AST level.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.handoff.bundle import assemble_bundle_v2, build_handoff
from forge_doctor_api.handoff.context import mint
from forge_doctor_api.handoff.protocol import (
    ForgeHandoff,
    ForgeRef,
    ForgeRequest,
    ForgeResult,
    build_result,
)


@dataclass(frozen=True, kw_only=True)
class DoctorBoundary:
    """Typed adapter: `ForgeRequest` in, `ForgeHandoff`/`ForgeResult` out.

    Construct with the ProjectContext of the target repo and an
    optional injected clock — the boundary never reaches for wall
    time, the network, or a subprocess.
    """

    context: ProjectContext
    clock: date | None = None

    def handle(self, request: ForgeRequest) -> ForgeHandoff:
        """Run the deterministic pipeline and emit a typed handoff.

        The request's `target` is informational only — the boundary
        was constructed over a `ProjectContext`; it never resolves,
        fetches, or re-roots anything.
        """
        from forge_doctor_api.scan import scan_project

        report = scan_project(self.context, today=self.clock)
        bundle = assemble_bundle_v2(
            report,
            service=report.project,
            findings=report.findings,
            unknowns=report.unknowns,
        )
        return build_handoff(report, bundle)

    def summarize(self, handoff: ForgeHandoff) -> ForgeResult:
        """Compact result view over an emitted handoff — status only.

        `status` is `ok` when the handoff carries no unknown refs,
        `partial` when it does. No payloads, no recomputation.
        """
        status = "partial" if handoff.unknowns else "ok"
        return build_result(
            status,
            summary=f"handoff {handoff.handoff_id}: "
                    f"{len(handoff.refs)} refs, "
                    f"{len(handoff.capabilities)} capabilities, "
                    f"{len(handoff.unknowns)} unknowns",
            refs=(ForgeRef(
                ref_id=mint("handoff", id=handoff.handoff_id),
                kind="handoff",
                sha256=handoff.handoff_id),),
        )

    def capabilities(self, request: ForgeRequest) -> ForgeResult:
        """Capability-only result for `requested_capabilities` queries."""
        from forge_doctor_api.scan import scan_project

        report = scan_project(self.context, today=self.clock)
        detected = {c.capability.value for c in report.capabilities}
        requested = set(request.requested_capabilities)
        missing = sorted(requested - detected)
        status = "ok" if not missing else "partial"
        summary = (
            f"{len(detected)} capabilities detected"
            + (f"; not evidenced: {', '.join(missing)}" if missing else ""))
        refs = tuple(
            ForgeRef(
                ref_id=mint("capability", id=c),
                kind="capability", entity=c,
                summary="not evidenced" if c in missing else "detected")
            for c in sorted(requested)) if requested else ()
        return build_result(status, summary=summary, refs=refs)


def handoff_to_member_fields(handoff: ForgeHandoff) -> dict[str, Any]:
    """Compact report-equivalent fields for fleet aggregation.

    Only what a `ForgeHandoff` truthfully carries — detected
    capabilities that unambiguously name a protocol style become
    style hints, unknown refs are preserved as subjects. Nothing is
    inferred from absence: no capability ⇒ no style claim.
    """
    _CAP_STYLE = {
        "ASYNCAPI": "async",
        "GRAPHQL_SUBSCRIPTIONS": "graphql",
        "GRPC_STREAMING": "grpc",
        "GRPC_CLIENT": "grpc",
    }
    styles = sorted({
        _CAP_STYLE[c.name] for c in handoff.capabilities
        if c.status == "detected" and c.name in _CAP_STYLE})
    return {
        "styles": tuple(styles),
        "unknown_subjects": tuple(
            u.entity or u.summary for u in handoff.unknowns),
        "analysis_rev": handoff.analysis_rev,
        "handoff_id": handoff.handoff_id,
    }
