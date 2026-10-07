"""Spec 059 — temporal snapshots + architectural regressions.

Snapshot ids are content hashes (deterministic, reorder-proof),
created_at is injected (never wall-clock), the store dir is created
only by explicit save, and every regression finding carries prev+cur
evidence references.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
    UnknownFact,
)
from forge_doctor_api.report import DoctorReport
from forge_doctor_api.temporal import (
    SnapshotError,
    SnapshotStore,
    architectural_regressions,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _report(
    *,
    findings: tuple[Finding, ...] = (),
    unknowns: tuple[UnknownFact, ...] = (),
    operations: tuple[str, ...] = (),
) -> DoctorReport:
    return DoctorReport(
        findings=findings, unknowns=unknowns, operations=operations)


def _finding(check_id: str, severity: Severity = Severity.HIGH) -> Finding:
    return Finding(
        id=check_id, title=check_id, description=check_id,
        severity=severity, confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        evidence=(Evidence(kind=EvidenceKind.STATIC,
                           source="t.yaml", summary="t"),))


def test_save_load_roundtrip(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    snap = store.save(_report(), label="v1", created_at=NOW)
    assert snap.id == snap.hash[:16]
    assert snap.created_at == NOW.isoformat(timespec="seconds")
    assert snap.report_ref == f"doctor://report/{snap.id}"
    loaded = store.report(snap.id)
    assert loaded.to_dict() == _report().to_dict()
    assert store.snapshot("v1").id == snap.id  # label lookup


def test_ids_are_content_hashes_reorder_invariant(tmp_path: Path) -> None:
    a = _report(operations=("GET /a", "GET /b"))
    b = _report(operations=("GET /b", "GET /a"))
    # operations order differs but the model sorts on encode -> same id
    s1 = SnapshotStore(tmp_path / "s").save(a, created_at=NOW)
    s2 = SnapshotStore(tmp_path / "s").save(b, created_at=NOW)
    assert s1.id == s2.id


def test_different_reports_different_ids(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s")
    s1 = store.save(_report(operations=("GET /a",)), created_at=NOW)
    s2 = store.save(_report(operations=("GET /z",)), created_at=NOW)
    assert s1.id != s2.id
    assert len(store.list()) == 2


def test_list_never_creates_dir(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "nope")
    assert store.list() == ()
    assert not (tmp_path / "nope").exists()


def test_missing_and_corrupt_snapshot(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "s")
    with pytest.raises(SnapshotError):
        store.report("absent")
    (tmp_path / "s").mkdir(parents=True)
    (tmp_path / "s" / "bad.json").write_text("{not json", "utf-8")
    with pytest.raises(SnapshotError):
        store.report("bad")


def test_regression_new_high_severity() -> None:
    prev = _report()
    cur = _report(findings=(_finding("OAS019"),))
    reg = architectural_regressions(prev, cur)
    kinds = {f.id for f in reg}
    assert "APITEMP002" in kinds
    f = next(f for f in reg if f.id == "APITEMP002")
    # prev + cur evidence refs (spec 059)
    sources = [e.source for e in f.evidence]
    assert "doctor://report/prev" in sources
    assert "doctor://report/cur" in sources


def test_regression_removed_operation() -> None:
    prev = _report(operations=("GET /gone", "GET /kept"))
    cur = _report(operations=("GET /kept",))
    reg = architectural_regressions(prev, cur)
    assert any(f.id == "APITEMP003" and "GET /gone" in f.description
               for f in reg)


def test_regression_newly_unknown_required_fact() -> None:
    prev = _report()
    cur = _report(unknowns=(UnknownFact(
        subject="routes", missing="route evidence",
        resolution="add source files"),))
    reg = architectural_regressions(prev, cur)
    assert any(f.id == "APITEMP004" for f in reg)


def test_no_regressions_on_identical_reports() -> None:
    r = _report(findings=(_finding("OAS019"),),
                operations=("GET /a",))
    assert architectural_regressions(r, r) == ()


def test_regressions_deterministic() -> None:
    prev = _report(operations=("GET /a", "GET /b"))
    cur = _report(
        findings=(_finding("OAS019"), _finding("APISC001",
                                               Severity.CRITICAL)),
        unknowns=(UnknownFact(subject="contracts",
                              missing="x", resolution="y"),))
    a = architectural_regressions(prev, cur)
    b = architectural_regressions(prev, cur)
    assert a == b
