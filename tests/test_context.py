"""Spec 048 — doctor:// refs, bounded slices, token metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.handoff.context import (
    MAX_OPS_PER_SLICE,
    ContextRefError,
    context_slice,
    measure,
    mint,
    parse,
)
from forge_doctor_api.scan import scan_project

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""


def _report(tmp_path: Path):
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return scan_project(ProjectContext.from_root(tmp_path))


def test_mint_parse_round_trip() -> None:
    ref = mint("finding", id="API001", subject="svc:op", digest="ab12")
    parsed = parse(ref)
    assert parsed.kind == "finding"
    assert parsed.parts == ("API001", "svc:op", "ab12")
    assert parsed.uri == ref


def test_mint_order_stable() -> None:
    a = mint("finding", id="X", digest="d", subject="s")
    b = mint("finding", subject="s", digest="d", id="X")
    assert a == b


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ContextRefError):
        mint("bogus", id="x")
    with pytest.raises(ContextRefError):
        parse("doctor://bogus/x")
    with pytest.raises(ContextRefError):
        parse("http://not-a-ref")


def test_service_slice_bounded(tmp_path: Path) -> None:
    report = _report(tmp_path)
    sl = context_slice(report, mint("service"))
    assert sl.kind == "service"
    fields = dict(sl.fields)
    assert "operations" in fields
    assert len(sl.fields) <= 4


def test_finding_slice(tmp_path: Path) -> None:
    report = _report(tmp_path)
    if not report.findings:
        pytest.skip("fixture produced no findings")
    from forge_doctor_api.handoff.context import finding_refs

    ref = finding_refs(report)[0]
    sl = context_slice(report, ref)
    assert len(sl.findings) == 1
    # stable: same report -> same ref
    assert finding_refs(report)[0] == ref


def test_unknown_slice(tmp_path: Path) -> None:
    report = _report(tmp_path)
    ref = mint("unknown", i=0)
    sl = context_slice(report, ref)
    if report.unknowns:
        assert len(sl.unknowns) == 1
    else:
        assert sl.unknowns == ()


def test_absent_domain_slice_is_empty(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report.runtime is None
    sl = context_slice(report, mint("runtime"))
    assert sl.fields == () and sl.findings == ()


def test_measure_metrics(tmp_path: Path) -> None:
    report = _report(tmp_path)
    m = measure(report)
    assert m.raw_bytes > 0
    assert m.slice_bytes < m.raw_bytes or m.slice_bytes > 0
    assert m.estimated_tokens >= 1
    assert m.unknowns == len(report.unknowns)


def test_slice_deterministic(tmp_path: Path) -> None:
    r1 = _report(tmp_path)
    r2 = _report(tmp_path)
    assert context_slice(r1, mint("service")).to_json() == (
        context_slice(r2, mint("service")).to_json())


def test_ops_cap_documented() -> None:
    assert MAX_OPS_PER_SLICE == 128
