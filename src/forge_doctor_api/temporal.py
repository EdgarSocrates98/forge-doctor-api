"""Spec 059 — temporal snapshots + architectural regressions.

Snapshots are explicit, opt-in artifacts under
`.forge-doctor/snapshots/` (or any dir the caller names — nothing is
auto-created outside an explicit `save`). `created_at` is always
injected: the engine never reads a wall clock. Ids are content
hashes — deterministic and reorder-proof.

`architectural_regressions` compares two reports and emits only
evidence-backed regression classes: new breaking changes, new
high-severity findings, removed operations, newly-unknown required
facts. Each finding carries both prev and cur evidence references.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    Severity,
)
from forge_doctor_api.report import DoctorReport

SNAPSHOT_DIR = ".forge-doctor/snapshots"


class SnapshotError(Exception):
    """Missing/corrupt snapshot, or store misuse."""


@dataclass(frozen=True, kw_only=True)
class Snapshot(Model):
    """One saved report point-in-time reference."""

    id: str                    # content hash of the stored report
    label: str
    created_at: str            # injected ISO timestamp
    report_ref: str            # doctor://report/{id}
    hash: str                  # report body sha256


# Fields that exist only under opt-in measurement flags
# (--stats-timing) — they never enter the canonical hash.
_NONCANONICAL_KEYS = frozenset({"duration_ms", "allocated_bytes"})


def _canon(value: Any) -> Any:
    """Deep-sort arrays so the hash is reorder-invariant.

    DoctorReport's contract treats emitted collections as unordered
    (deterministically sorted) — canonicalization makes the snapshot
    id stable even if an upstream caller hands us a differently
    ordered equivalent report.
    """
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in sorted(value.items())
                if k not in _NONCANONICAL_KEYS}
    if isinstance(value, list):
        canon = [_canon(v) for v in value]
        try:
            return sorted(canon, key=lambda v: json.dumps(
                v, sort_keys=True, default=str))
        except TypeError:
            return canon
    return value


def _report_hash(report: DoctorReport) -> str:
    body = json.dumps(
        _canon(report.to_dict()), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class SnapshotStore:
    """File-based snapshot storage — created only by explicit save."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, snap_id: str) -> Path:
        return self._root / f"{snap_id}.json"

    def save(self, report: DoctorReport, *, label: str = "",
             created_at: datetime | None = None) -> Snapshot:
        body = _report_hash(report)
        snap = Snapshot(
            id=body[:16], label=label or body[:16],
            created_at=created_at.isoformat(timespec="seconds")
            if created_at is not None else "",
            report_ref=f"doctor://report/{body[:16]}", hash=body)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(snap.id).write_text(
            json.dumps({"snapshot": snap.to_dict(),
                        "report": report.to_dict()},
                       sort_keys=True), encoding="utf-8")
        return snap

    def list(self) -> tuple[Snapshot, ...]:
        if not self._root.is_dir():
            return ()
        out: list[Snapshot] = []
        for f in sorted(self._root.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(Snapshot.from_dict(data["snapshot"]))
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return tuple(sorted(out, key=lambda s: (s.created_at, s.id)))

    def _load(self, snap_id: str) -> dict[str, Any]:
        path = self._path(snap_id)
        if not path.is_file():
            matches = [s for s in self.list()
                       if s.id.startswith(snap_id) or s.label == snap_id]
            if len(matches) == 1:
                path = self._path(matches[0].id)
            else:
                raise SnapshotError(f"no snapshot {snap_id!r}")
        try:
            data: dict[str, Any] = json.loads(
                path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise SnapshotError(f"corrupt snapshot {snap_id!r}") from e
        return data

    def snapshot(self, snap_id: str) -> Snapshot:
        return Snapshot.from_dict(self._load(snap_id)["snapshot"])

    def report(self, snap_id: str) -> DoctorReport:
        return DoctorReport.from_dict(self._load(snap_id)["report"])


# -- regressions -------------------------------------------------------------

_REQUIRED_DOMAIN_FIELDS = (
    "contracts", "routes", "clients", "graph", "runtime",
    "security", "reliability",
)


def _ev(prev_ref: str, cur_ref: str, summary: str) -> tuple[Evidence, ...]:
    return (
        Evidence(kind=EvidenceKind.DERIVED, source=prev_ref,
                 summary=f"previous snapshot: {summary}"),
        Evidence(kind=EvidenceKind.DERIVED, source=cur_ref,
                 summary=f"current snapshot: {summary}"),
    )


def architectural_regressions(
    prev: DoctorReport,
    cur: DoctorReport,
    *,
    prev_ref: str = "doctor://report/prev",
    cur_ref: str = "doctor://report/cur",
) -> tuple[Finding, ...]:
    """Evidence-backed regression classes between two snapshots."""
    out: list[Finding] = []

    if cur.diff is not None:
        for change in cur.diff.changes:
            if change.classification is CompatibilityClass.BREAKING:
                out.append(Finding(
                    id="APITEMP001",
                    title="Breaking contract change since snapshot",
                    description=(
                        f"{change.kind} {change.subject} is classified "
                        "BREAKING relative to the previous snapshot"),
                    severity=Severity.HIGH, confidence=Confidence.HIGH,
                    evidence_kind=EvidenceKind.DERIVED,
                    evidence=_ev(prev_ref, cur_ref,
                                 f"{change.kind}:{change.subject}")))

    prev_f = {(f.id, f.entity_ids[0] if f.entity_ids else "")
              for f in prev.findings}
    for f in cur.findings:
        key = (f.id, f.entity_ids[0] if f.entity_ids else "")
        if f.severity in (Severity.CRITICAL, Severity.HIGH) \
                and key not in prev_f:
            out.append(Finding(
                id="APITEMP002",
                title="New high-severity finding since snapshot",
                description=f"{f.id}: {f.title}",
                severity=Severity.HIGH, confidence=f.confidence,
                evidence_kind=EvidenceKind.DERIVED,
                evidence=_ev(prev_ref, cur_ref, f.id)))

    prev_ops = set(prev.operations) | {
        k for k, _ in (prev.contracts.digests if prev.contracts else ())}
    cur_ops = set(cur.operations) | {
        k for k, _ in (cur.contracts.digests if cur.contracts else ())}
    for op in sorted(prev_ops - cur_ops):
        out.append(Finding(
            id="APITEMP003",
            title="Operation removed since snapshot",
            description=f"{op} existed in the previous snapshot and is "
                        "absent now",
            severity=Severity.HIGH, confidence=Confidence.HIGH,
            evidence_kind=EvidenceKind.DERIVED,
            evidence=_ev(prev_ref, cur_ref, op)))

    prev_u = {(u.subject, u.missing) for u in prev.unknowns}
    for u in cur.unknowns:
        if (u.subject, u.missing) in prev_u:
            continue
        domain = u.subject.split(":", 1)[0]
        if domain in _REQUIRED_DOMAIN_FIELDS or u.subject in (
                "routes",):
            out.append(Finding(
                id="APITEMP004",
                title="Required fact newly unknown since snapshot",
                description=(
                    f"{u.subject}: {u.missing} was not unknown in the "
                    "previous snapshot"),
                severity=Severity.MEDIUM, confidence=Confidence.HIGH,
                evidence_kind=EvidenceKind.DERIVED,
                evidence=_ev(prev_ref, cur_ref, u.subject),
                unknowns=(u,)))

    return tuple(out)
