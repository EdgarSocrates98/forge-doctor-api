"""§26 Forge Protocol — typed, versioned cross-product contracts.

The Doctor produces facts; API Forge consumes them; The Forger routes.
These models are the only exchange surface: frozen, deterministic,
strictly parsed (unknown fields rejected unless `x-*` extension
namespace), and versioned (`PROTOCOL_VERSION = 1`).

Serialization uses the `Model.to_dict()` machinery; `parse_*` returns
typed objects or raises `ProtocolError` — never silently coerces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Self

from forge_doctor_api.core.models import Model

PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """Strict parse failure: unknown field, wrong type, bad version."""


def _reject_unknown(data: dict[str, Any], known: set[str], model: str) -> None:
    extra = set(data) - known
    unknown = {k for k in extra if not k.startswith("x-")}
    if unknown:
        raise ProtocolError(
            f"{model}: unknown field(s) {sorted(unknown)} "
            "(extension fields must use the x-* namespace)")


def _req(data: dict[str, Any], key: str, model: str) -> Any:
    if key not in data:
        raise ProtocolError(f"{model}: missing required field {key!r}")
    return data[key]


def _version_check(data: dict[str, Any], model: str) -> None:
    version = data.get("protocol_version", PROTOCOL_VERSION)
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            f"{model}: protocol_version {version!r} unsupported "
            f"(expected {PROTOCOL_VERSION})")


@dataclass(frozen=True, kw_only=True)
class ForgeRef(Model):
    """A typed reference: context/evidence/finding/unknown (§26)."""

    ref_id: str
    kind: str
    entity: str | None = None
    sha256: str | None = None
    summary: str = ""

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "ref_id", "kind", "entity", "sha256", "summary"}, "ForgeRef")
        return cls(
            ref_id=str(_req(data, "ref_id", "ForgeRef")),
            kind=str(_req(data, "kind", "ForgeRef")),
            entity=data.get("entity"),
            sha256=data.get("sha256"),
            summary=str(data.get("summary", "")),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeCapability(Model):
    """A capability the Doctor observed (status, never fabricated)."""

    name: str
    status: str
    unknowns: tuple[ForgeRef, ...] = ()

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {"name", "status", "unknowns"},
                        "ForgeCapability")
        return cls(
            name=str(_req(data, "name", "ForgeCapability")),
            status=str(_req(data, "status", "ForgeCapability")),
            unknowns=tuple(
                ForgeRef.parse(u) for u in data.get("unknowns", ())),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeRequest(Model):
    """§26 consumer -> Doctor request envelope."""

    protocol_version: int = PROTOCOL_VERSION
    request_id: str = ""
    target: str = ""
    requested_capabilities: tuple[str, ...] = ()
    clock: str | None = None  # injected logical clock, never wall time

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "request_id", "target",
            "requested_capabilities", "clock"}, "ForgeRequest")
        _version_check(data, "ForgeRequest")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            request_id=str(data.get("request_id", "")),
            target=str(_req(data, "target", "ForgeRequest")),
            requested_capabilities=tuple(
                str(c) for c in data.get("requested_capabilities", ())),
            clock=data.get("clock"),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeHandoff(Model):
    """§26 handoff envelope: bundle ref + typed content refs."""

    protocol_version: int = PROTOCOL_VERSION
    handoff_id: str = ""
    bundle_ref: str = ""
    analysis_rev: str | None = None
    refs: tuple[ForgeRef, ...] = ()
    capabilities: tuple[ForgeCapability, ...] = ()
    unknowns: tuple[ForgeRef, ...] = ()

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "handoff_id", "bundle_ref",
            "analysis_rev", "refs", "capabilities", "unknowns"},
            "ForgeHandoff")
        _version_check(data, "ForgeHandoff")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            handoff_id=str(_req(data, "handoff_id", "ForgeHandoff")),
            bundle_ref=str(_req(data, "bundle_ref", "ForgeHandoff")),
            analysis_rev=data.get("analysis_rev"),
            refs=tuple(ForgeRef.parse(r) for r in data.get("refs", ())),
            capabilities=tuple(
                ForgeCapability.parse(c)
                for c in data.get("capabilities", ())),
            unknowns=tuple(
                ForgeRef.parse(u) for u in data.get("unknowns", ())),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeReceipt(Model):
    """§26 consumer acknowledgement — links result back to analysis_rev."""

    protocol_version: int = PROTOCOL_VERSION
    analysis_rev: str = ""
    handoff_id: str = ""
    consumer: str = ""
    result_link: str | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "analysis_rev", "handoff_id",
            "consumer", "result_link"}, "ForgeReceipt")
        _version_check(data, "ForgeReceipt")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            analysis_rev=str(_req(data, "analysis_rev", "ForgeReceipt")),
            handoff_id=str(_req(data, "handoff_id", "ForgeReceipt")),
            consumer=str(_req(data, "consumer", "ForgeReceipt")),
            result_link=data.get("result_link"),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeResult(Model):
    """§26 typed result surface (status + summary + refs, no payloads)."""

    protocol_version: int = PROTOCOL_VERSION
    status: str = ""
    summary: str = ""
    refs: tuple[ForgeRef, ...] = ()

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "status", "summary", "refs"},
            "ForgeResult")
        _version_check(data, "ForgeResult")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            status=str(_req(data, "status", "ForgeResult")),
            summary=str(data.get("summary", "")),
            refs=tuple(ForgeRef.parse(r) for r in data.get("refs", ())),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeRoute(Model):
    """§26 routing record — source -> destination via capability."""

    protocol_version: int = PROTOCOL_VERSION
    route_id: str = ""
    source: str = ""
    destination: str = ""
    capability: str = ""

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "route_id", "source", "destination",
            "capability"}, "ForgeRoute")
        _version_check(data, "ForgeRoute")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            route_id=str(_req(data, "route_id", "ForgeRoute")),
            source=str(_req(data, "source", "ForgeRoute")),
            destination=str(_req(data, "destination", "ForgeRoute")),
            capability=str(data.get("capability", "")),
        )


def parse_payload(model: type[Model], text: str) -> Any:
    """Strict JSON -> protocol model. Errors are ProtocolError."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError(f"{model.__name__}: expected object payload")
    parse = getattr(model, "parse", None)
    if parse is None:
        raise ProtocolError(f"{model.__name__}: not a protocol model")
    return parse(data)


def build_request(
    target: str,
    *,
    request_id: str = "",
    capabilities: tuple[str, ...] = (),
    clock: str | None = None,
) -> ForgeRequest:
    """Deterministic request builder — caller supplies identity/clock."""
    return ForgeRequest(
        request_id=request_id,
        target=target,
        requested_capabilities=tuple(sorted(capabilities)),
        clock=clock,
    )


def build_receipt(
    handoff: ForgeHandoff,
    consumer: str,
    *,
    result_link: str | None = None,
) -> ForgeReceipt:
    """Receipt bound to the handoff's analysis revision."""
    return ForgeReceipt(
        analysis_rev=handoff.analysis_rev or "",
        handoff_id=handoff.handoff_id,
        consumer=consumer,
        result_link=result_link,
    )


def build_result(
    status: str,
    *,
    summary: str = "",
    refs: tuple[ForgeRef, ...] = (),
) -> ForgeResult:
    return ForgeResult(
        status=status, summary=summary,
        refs=tuple(sorted(refs, key=lambda r: r.ref_id)))
