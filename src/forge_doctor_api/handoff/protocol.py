"""§26 Forge Protocol — typed, versioned cross-product contracts.

The Doctor produces facts; API Forge consumes them; The Forger routes.
These models are the only exchange surface: frozen, deterministic,
strictly parsed (unknown fields rejected unless `x-*` extension
namespace), and versioned (`PROTOCOL_VERSION = 1`).

Serialization uses the `Model.to_dict()` machinery; `parse_*` returns
typed objects or raises `ProtocolError` — never silently coerces.

Protocol v2 (spec 075): `ForgeRequest` is slimmed to
`capabilities`/`context_refs`/`delta`; v1 payloads keep parsing —
`requested_capabilities` is honored as the v1 alias. Emission is
always v2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Self

from forge_doctor_api.core.models import Model

PROTOCOL_VERSION = 2
_SUPPORTED_VERSIONS = (1, 2)


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
    if version not in _SUPPORTED_VERSIONS:
        raise ProtocolError(
            f"{model}: protocol_version {version!r} unsupported "
            f"(expected one of {_SUPPORTED_VERSIONS})")


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
class RequestDelta(Model):
    """§26 v2 incremental-analysis descriptor on a `ForgeRequest`.

    `baseline_ref` names the prior analysis to diff against (a
    `doctor://handoff/...` or snapshot reference); `changed_files`
    hints the changed surface. The boundary resolves the baseline —
    the request never carries report payloads.
    """

    baseline_ref: str = ""
    changed_files: tuple[str, ...] = ()

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {"baseline_ref", "changed_files"},
                        "RequestDelta")
        return cls(
            baseline_ref=str(_req(data, "baseline_ref", "RequestDelta")),
            changed_files=tuple(sorted(
                str(f) for f in data.get("changed_files", ()))),
        )


@dataclass(frozen=True, kw_only=True)
class ForgeRequest(Model):
    """§26 consumer -> Doctor request envelope (v2 slim shape).

    Carries identity, target, capability query, resolvable context
    refs and an optional delta descriptor — nothing else. v1
    `requested_capabilities` payloads are honored via alias.
    """

    protocol_version: int = PROTOCOL_VERSION
    request_id: str = ""
    target: str = ""
    capabilities: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    delta: RequestDelta | None = None
    clock: str | None = None  # injected logical clock, never wall time

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        _reject_unknown(data, {
            "protocol_version", "request_id", "target", "capabilities",
            "requested_capabilities", "context_refs", "delta", "clock"},
            "ForgeRequest")
        _version_check(data, "ForgeRequest")
        caps = tuple(str(c) for c in data.get("capabilities", ()))
        legacy = tuple(
            str(c) for c in data.get("requested_capabilities", ()))
        if caps and legacy:
            raise ProtocolError(
                "ForgeRequest: 'capabilities' and v1 alias "
                "'requested_capabilities' must not both be set")
        delta_raw = data.get("delta")
        return cls(
            protocol_version=int(
                data.get("protocol_version", PROTOCOL_VERSION)),
            request_id=str(data.get("request_id", "")),
            target=str(_req(data, "target", "ForgeRequest")),
            capabilities=caps or legacy,
            context_refs=tuple(
                str(r) for r in data.get("context_refs", ())),
            delta=RequestDelta.parse(delta_raw)
                  if delta_raw is not None else None,
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
    context_refs: tuple[str, ...] = (),
    delta: RequestDelta | None = None,
    clock: str | None = None,
) -> ForgeRequest:
    """Deterministic request builder — caller supplies identity/clock."""
    return ForgeRequest(
        request_id=request_id,
        target=target,
        capabilities=tuple(sorted(capabilities)),
        context_refs=tuple(sorted(context_refs)),
        delta=delta,
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
