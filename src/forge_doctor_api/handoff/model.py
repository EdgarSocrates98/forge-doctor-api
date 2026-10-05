"""§134-§138, §215 handoff and routing models.

Bundles are compact by design (§135): references + summaries, never raw
repository payloads. Cross-domain links are ExternalReferences only —
graphs are never merged (§138).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from forge_doctor_api.core.graph import EdgeExport
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    Model,
    UnknownFact,
)
from forge_doctor_api.handoff.protocol import ForgeCapability
from forge_doctor_api.safefix.model import Remediation

if TYPE_CHECKING:
    from forge_doctor_api.handoff.delta import DeltaContext

# §135/§075 — per-section entry budgets for handoff payloads. A bundle
# is a *reference surface*; each budget provably caps growth. Sections
# over budget are truncated deterministically and every truncation is
# recorded as an UnknownFact — never a silent drop.
HANDOFF_BUDGET: dict[str, int] = {
    "operations": 2048,
    "contracts": 256,
    "findings": 512,
    "breaking_changes": 512,
    "clients_affected": 512,
    "runtime_regressions": 256,
    "security_candidates": 256,
    "reliability_signals": 256,
    "external_references": 256,
    "remediation_candidates": 128,
    "unknowns": 512,
    "domain_sha256": 64,
    "context_refs": 2048,
    "capabilities": 128,
    "graph_edges": 2048,
}

_V2_FIELDS = (
    "handoff_version", "handoff_id", "analysis_rev", "domain_sha256",
    "context_refs", "capabilities", "graph_edges", "delta",
)


def _budget_unknown(
    section: str, *, dropped: int, total: int, limit: int,
) -> UnknownFact:
    return UnknownFact(
        subject=f"handoff:{section}",
        missing=f"budget_exceeded: {dropped} of {total} entries "
                f"truncated (limit {limit})",
        resolution=(
            f"raise the {section} handoff budget or split the "
            "handoff"),
    )


# Stable sort keys per budgeted section — truncation is always
# deterministic: sort by a stable key first, then take N.
_BUDGET_KEYS: dict[str, Any] = {
    "operations": lambda s: s,
    "contracts": lambda s: s,
    "findings": lambda f: (
        f.id, f.entity_ids[0] if f.entity_ids else "", f.title),
    "breaking_changes": lambda s: s,
    "clients_affected": lambda s: s,
    "runtime_regressions": lambda s: s,
    "security_candidates": lambda s: s,
    "reliability_signals": lambda s: s,
    "external_references": lambda r: (
        r.target_domain, r.target_ref, r.source_id, r.relation),
    "remediation_candidates": lambda r: (
        r.finding_id or "", r.target, r.proposed_change),
    "unknowns": lambda u: (u.subject, u.missing, u.resolution),
    "domain_sha256": lambda p: p,
    "context_refs": lambda s: s,
    "capabilities": lambda c: c.name,
    "graph_edges": lambda e: (e.from_id, e.to_id, e.kind),
}


@dataclass(frozen=True, kw_only=True)
class ExternalReference(Model):
    """§138 a reference to an entity owned by another domain.

    `target_ref` is opaque to this domain — the reference declares that a
    handoff point exists, not what the foreign graph looks like.
    """

    source_id: str
    target_domain: str
    target_ref: str
    relation: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiHandoffBundle(Model):
    """§134 compact handoff unit for API Forge / The Forger.

    `handoff_version=2` adds deterministic identity + content
    addressing: `handoff_id` (sha256 of the bundle body),
    `analysis_rev` (sha256 of the source report), per-domain content
    hashes, `doctor://` context refs and typed capabilities. V1 keeps
    these fields empty/None — identical serialized shape.
    """

    schema_version: str = "1.0"
    service: str | None = None
    operations: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    breaking_changes: tuple[str, ...] = ()
    clients_affected: tuple[str, ...] = ()
    runtime_regressions: tuple[str, ...] = ()
    security_candidates: tuple[str, ...] = ()
    reliability_signals: tuple[str, ...] = ()
    external_references: tuple[ExternalReference, ...] = ()
    remediation_candidates: tuple[Remediation, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
    knowledge_versions: dict[str, str] = field(default_factory=dict)

    # --- V2 (§134/§26) — empty on V1 -------------------------------------
    handoff_version: int = 1
    handoff_id: str = ""
    analysis_rev: str | None = None
    domain_sha256: tuple[tuple[str, str], ...] = ()
    context_refs: tuple[str, ...] = ()
    capabilities: tuple[ForgeCapability, ...] = ()
    graph_edges: tuple[EdgeExport, ...] = ()
    # spec 075 — first-class delta context (present when the request
    # carried a resolvable delta descriptor)
    delta: DeltaContext | None = None

    def body_sha256(self) -> str:
        """Content hash over the V1 body — V2 fields excluded so
        identity stays stable across envelope projections/deltas."""
        body = self.to_dict()
        for k in _V2_FIELDS:
            body.pop(k, None)
        canonical = json.dumps(
            body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def bounded(
        self, budget: dict[str, int] | None = None,
    ) -> ApiHandoffBundle:
        """§135 deterministic size cap — sort then take N per section.

        Every truncation appends an `UnknownFact` recording the budget
        breach (`budget_exceeded`); nothing is dropped silently. On V2
        the content hash is recomputed so identity stays truthful.
        """
        caps = dict(HANDOFF_BUDGET)
        if budget:
            caps.update({k: int(v) for k, v in budget.items()})
        markers: list[UnknownFact] = []
        updates: dict[str, Any] = {}
        for name, limit in sorted(caps.items()):
            if name == "unknowns":
                continue  # handled after markers are collected
            value = getattr(self, name, None)
            if value is None:
                continue
            ordered = tuple(sorted(value, key=_BUDGET_KEYS[name]))
            if len(ordered) > limit:
                updates[name] = ordered[:max(0, limit)]
                markers.append(_budget_unknown(
                    name, dropped=len(ordered) - limit,
                    total=len(ordered), limit=limit))
            elif ordered != value:
                updates[name] = ordered
        unknowns = tuple(sorted(
            (*self.unknowns, *markers),
            key=_BUDGET_KEYS["unknowns"]))
        u_limit = caps["unknowns"]
        if len(unknowns) > u_limit:
            unknowns = (
                *unknowns[:max(0, u_limit - 1)],
                _budget_unknown(
                    "unknowns", dropped=len(unknowns) - u_limit + 1,
                    total=len(unknowns), limit=u_limit))
        updates["unknowns"] = unknowns
        result = replace(self, **updates)
        if result.handoff_version == 2:
            result = replace(result, handoff_id=result.body_sha256())
        return result


@dataclass(frozen=True, kw_only=True)
class ForgerRequest(Model):
    """§136/§215 structured request shape routed by The Forger."""

    task: str
    domain: str = "api"
    subject: str | None = None


@dataclass(frozen=True, kw_only=True)
class ForgerRoute(Model):
    """§215 routing decision — a declared destination, never an execution."""

    domain: str
    handler: str
    reason: str
    chain: tuple[str, ...] = ()
    references: tuple[ExternalReference, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
