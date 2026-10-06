"""Spec 046 — Forge Protocol models, strict parse, deterministic build."""

from __future__ import annotations

import pytest

from forge_doctor_api.handoff.protocol import (
    PROTOCOL_VERSION,
    ForgeCapability,
    ForgeHandoff,
    ForgeReceipt,
    ForgeRef,
    ForgeRequest,
    ForgeResult,
    ForgeRoute,
    ProtocolError,
    RequestDelta,
    build_receipt,
    build_request,
    build_result,
    parse_payload,
)


def test_request_round_trip() -> None:
    req = build_request(
        "svc", request_id="r1",
        capabilities=("b", "a"), clock="2026-01-01")
    assert req.protocol_version == PROTOCOL_VERSION
    assert req.capabilities == ("a", "b")  # sorted
    text = req.to_json()
    back = ForgeRequest.parse(req.to_dict())
    assert back == req
    # deterministic serialization
    assert text == build_request(
        "svc", request_id="r1",
        capabilities=("a", "b"), clock="2026-01-01").to_json()


def test_request_slim_shape() -> None:
    req = build_request(
        "svc", request_id="r2",
        capabilities=("OPENAPI_32",),
        context_refs=("doctor://handoff/h1", "doctor://service"),
        delta=RequestDelta(
            baseline_ref="doctor://handoff/h1",
            changed_files=("api.yaml",)))
    data = req.to_dict()
    assert data["capabilities"] == ["OPENAPI_32"]
    assert data["context_refs"] == [
        "doctor://handoff/h1", "doctor://service"]
    assert data["delta"]["baseline_ref"] == "doctor://handoff/h1"
    back = ForgeRequest.parse(data)
    assert back == req
    assert back.delta is not None
    assert back.delta.baseline_ref == "doctor://handoff/h1"


def test_request_v1_alias_compat() -> None:
    """v1 payloads: `requested_capabilities` parses into `capabilities`."""
    req = ForgeRequest.parse({
        "protocol_version": 1,
        "request_id": "r1", "target": "svc",
        "requested_capabilities": ["MTLS", "OPENAPI_32"]})
    assert req.capabilities == ("MTLS", "OPENAPI_32")
    assert req.context_refs == ()
    assert req.delta is None
    # both spellings in one payload is a conflict, not a merge
    with pytest.raises(ProtocolError):
        ForgeRequest.parse({
            "target": "svc",
            "capabilities": ["A"],
            "requested_capabilities": ["B"]})


def test_parse_rejects_unknown_fields() -> None:
    with pytest.raises(ProtocolError):
        ForgeRequest.parse({"target": "s", "bogus": 1})
    # x-* extension namespace tolerated
    ok = ForgeRequest.parse({"target": "s", "x-vendor": {"k": 1}})
    assert ok.target == "s"


def test_version_mismatch_rejected() -> None:
    with pytest.raises(ProtocolError):
        ForgeHandoff.parse({
            "protocol_version": 99, "handoff_id": "h",
            "bundle_ref": "b"})


def test_missing_required_rejected() -> None:
    with pytest.raises(ProtocolError):
        ForgeReceipt.parse({"handoff_id": "h"})


def test_handoff_receipt_link() -> None:
    handoff = ForgeHandoff(
        handoff_id="h1", bundle_ref="doctor://handoff/h1",
        analysis_rev="abc",
        refs=(ForgeRef(ref_id="doctor://service", kind="service"),),
        capabilities=(ForgeCapability(name="RETRY", status="detected"),),
    )
    receipt = build_receipt(handoff, "api-forge", result_link="run://9")
    assert receipt.analysis_rev == "abc"
    assert receipt.handoff_id == "h1"
    assert receipt.consumer == "api-forge"
    assert ForgeReceipt.parse(receipt.to_dict()) == receipt


def test_result_sorted_refs() -> None:
    res = build_result("ok", refs=(
        ForgeRef(ref_id="b", kind="finding"),
        ForgeRef(ref_id="a", kind="finding"),
    ))
    assert [r.ref_id for r in res.refs] == ["a", "b"]


def test_parse_payload_strict() -> None:
    assert parse_payload(ForgeResult, '{"status":"ok"}').status == "ok"
    with pytest.raises(ProtocolError):
        parse_payload(ForgeResult, "[1]")
    with pytest.raises(ProtocolError):
        parse_payload(ForgeResult, "{not json")


def test_route_model() -> None:
    route = ForgeRoute(
        route_id="r1", source="doctor", destination="api-forge",
            capability="scan")
    assert ForgeRoute.parse(route.to_dict()) == route
