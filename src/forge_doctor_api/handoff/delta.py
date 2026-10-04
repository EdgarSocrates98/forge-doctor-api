"""§37 delta context — prev/current report diff for incremental handoffs.

Consumers that already hold a prior report should not re-ingest the
world. `compute_delta` emits a compact, fully sorted `DeltaContext`:
what appeared, what disappeared, what changed — nothing else.

Identity rules (deterministic, reorder-proof):
- finding: keyed by (check id, primary entity). A digest of the
  full content decides "changed" vs "unchanged" — reordered input
  never produces a delta row.
- unknown: keyed by (subject, missing).
- graph entity: keyed by service id (DomainSummary projection).
- capability: keyed by name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from forge_doctor_api.core.models import Finding, Model
from forge_doctor_api.report import DoctorReport

_DELTA_DOMAIN_FIELDS = (
    "contracts", "routes", "clients", "graph", "gateway", "mesh",
    "infrastructure", "cache", "runtime", "security", "reliability",
    "policies", "twin", "fanout", "migration", "impact",
)


@dataclass(frozen=True, kw_only=True)
class DeltaContext(Model):
    """§37 compact delta between two DoctorReports."""

    initial: bool = False
    analysis_rev_prev: str | None = None
    analysis_rev_cur: str | None = None
    findings_added: tuple[str, ...] = ()
    findings_removed: tuple[str, ...] = ()
    findings_changed: tuple[str, ...] = ()
    evidence_added: int = 0
    evidence_removed: int = 0
    operations_added: tuple[str, ...] = ()
    operations_removed: tuple[str, ...] = ()
    operations_changed: tuple[str, ...] = ()
    graph_entities_added: tuple[str, ...] = ()
    graph_entities_removed: tuple[str, ...] = ()
    unknowns_added: tuple[str, ...] = ()
    unknowns_removed: tuple[str, ...] = ()
    domains_added: tuple[str, ...] = ()
    domains_removed: tuple[str, ...] = ()
    capabilities_added: tuple[str, ...] = ()
    capabilities_removed: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (
            self.findings_added or self.findings_removed
            or self.findings_changed or self.operations_added
            or self.operations_removed or self.operations_changed
            or self.graph_entities_added
            or self.graph_entities_removed or self.unknowns_added
            or self.unknowns_removed or self.domains_added
            or self.domains_removed or self.capabilities_added
            or self.capabilities_removed
            or self.evidence_added or self.evidence_removed)


def _finding_key(f: Finding) -> str:
    subject = f.entity_ids[0] if f.entity_ids else ""
    return f"{f.id}|{subject}"


def _finding_digest(f: Finding) -> str:
    return hashlib.sha256(
        f.to_json().encode("utf-8")).hexdigest()[:16]


def _unknown_key(u: object) -> str:
    return f"{u.subject}|{u.missing}"  # type: ignore[attr-defined]


def compute_delta(
    prev: DoctorReport | None,
    cur: DoctorReport,
) -> DeltaContext:
    """prev -> cur delta. `prev=None` yields the flagged initial delta."""
    if prev is None:
        return DeltaContext(
            initial=True,
            analysis_rev_cur=cur.analysis_rev,
            findings_added=tuple(_finding_key(f) for f in cur.findings),
            evidence_added=sum(len(f.evidence) for f in cur.findings),
            operations_added=tuple(
                k for k, _ in (cur.contracts.digests if cur.contracts
                               else ())),
            graph_entities_added=cur.graph.ids if cur.graph else (),
            unknowns_added=tuple(_unknown_key(u) for u in cur.unknowns),
            domains_added=tuple(
                n for n in _DELTA_DOMAIN_FIELDS
                if getattr(cur, n, None) is not None),
            capabilities_added=tuple(
                c.capability.value for c in cur.capabilities),
        )

    prev_f = {_finding_key(f): f for f in prev.findings}
    cur_f = {_finding_key(f): f for f in cur.findings}
    added = sorted(set(cur_f) - set(prev_f))
    removed = sorted(set(prev_f) - set(cur_f))
    changed = sorted(
        k for k in set(prev_f) & set(cur_f)
        if _finding_digest(prev_f[k]) != _finding_digest(cur_f[k]))

    ev_added = sum(len(cur_f[k].evidence) for k in added) + sum(
        max(0, len(cur_f[k].evidence) - len(prev_f[k].evidence))
        for k in changed)
    ev_removed = sum(len(prev_f[k].evidence) for k in removed) + sum(
        max(0, len(prev_f[k].evidence) - len(cur_f[k].evidence))
        for k in changed)

    prev_ops = dict(prev.contracts.digests) if prev.contracts else {}
    cur_ops = dict(cur.contracts.digests) if cur.contracts else {}

    prev_g = set(prev.graph.ids) if prev.graph else set()
    cur_g = set(cur.graph.ids) if cur.graph else set()

    prev_u = {_unknown_key(u) for u in prev.unknowns}
    cur_u = {_unknown_key(u) for u in cur.unknowns}

    prev_domains = {n for n in _DELTA_DOMAIN_FIELDS
                    if getattr(prev, n, None) is not None}
    cur_domains = {n for n in _DELTA_DOMAIN_FIELDS
                   if getattr(cur, n, None) is not None}

    prev_caps = {c.capability.value for c in prev.capabilities}
    cur_caps = {c.capability.value for c in cur.capabilities}

    return DeltaContext(
        analysis_rev_prev=prev.analysis_rev,
        analysis_rev_cur=cur.analysis_rev,
        findings_added=tuple(added),
        findings_removed=tuple(removed),
        findings_changed=tuple(changed),
        evidence_added=ev_added,
        evidence_removed=ev_removed,
        operations_added=tuple(sorted(set(cur_ops) - set(prev_ops))),
        operations_removed=tuple(sorted(set(prev_ops) - set(cur_ops))),
        operations_changed=tuple(sorted(
            k for k in set(prev_ops) & set(cur_ops)
            if prev_ops[k] != cur_ops[k])),
        graph_entities_added=tuple(sorted(cur_g - prev_g)),
        graph_entities_removed=tuple(sorted(prev_g - cur_g)),
        unknowns_added=tuple(sorted(cur_u - prev_u)),
        unknowns_removed=tuple(sorted(prev_u - cur_u)),
        domains_added=tuple(sorted(cur_domains - prev_domains)),
        domains_removed=tuple(sorted(prev_domains - cur_domains)),
        capabilities_added=tuple(sorted(cur_caps - prev_caps)),
        capabilities_removed=tuple(sorted(prev_caps - cur_caps)),
    )
