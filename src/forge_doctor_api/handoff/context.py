"""§34-§35 context broker: `doctor://` refs + bounded context slices.

Every piece of report content is addressable by a deterministic URI.
Refs mint identically for identical reports (digest-based where the
grammar carries a digest), so two agents can exchange references
without exchanging payloads.

Slices are the token-economy surface: a `ContextSlice` carries only the
fields the requested kind needs, bounded by documented caps — never a
raw report section.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Finding,
    Model,
    UnknownFact,
)
from forge_doctor_api.report import DoctorReport

CONTEXT_REF_PREFIX = "doctor://"
CONTEXT_REF_VERSION = "v1"

# §35 addressable kinds. Unknown kinds are a hard error, never guessed.
REF_KINDS = frozenset({
    "service",
    "operation",
    "contract",
    "finding",
    "unknown",
    "graph",
    "runtime",
    "capability",
    "handoff",
})

# Slice caps — documented bounds that keep every slice small.
MAX_OPS_PER_SLICE = 128
MAX_FINDINGS_PER_SLICE = 64
MAX_GRAPH_EDGES = 64
MAX_CAPABILITIES = 64
_CHARS_PER_TOKEN = 4  # documented heuristic, not a tokenizer


class ContextRefError(ValueError):
    """Malformed doctor:// URI or unknown kind."""


@dataclass(frozen=True, kw_only=True)
class ContextRef(Model):
    """Parsed `doctor://` reference."""

    kind: str
    parts: tuple[str, ...] = ()

    @property
    def uri(self) -> str:
        suffix = "/".join(self.parts)
        return f"{CONTEXT_REF_PREFIX}{self.kind}" + (
            f"/{suffix}" if suffix else "")


@dataclass(frozen=True, kw_only=True)
class ContextSlice(Model):
    """Minimal bounded view of report content for one ref kind."""

    ref: str
    kind: str
    fields: tuple[tuple[str, str], ...] = ()
    findings: tuple[Finding, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, kw_only=True)
class ContextMetrics(Model):
    """Token-economy measurement of a report (documented heuristics)."""

    raw_bytes: int
    slice_bytes: int
    estimated_tokens: int
    evidence_refs: int
    unknowns: int


def _norm(value: object) -> str:
    """Digest-safe path component."""
    text = str(value)
    return "/".join(p for p in text.replace("\\", "/").split("/") if p)


# Canonical part order — identity first, digest last (readable URIs).
_PART_ORDER = {"id": 0, "subject": 1, "i": 2, "digest": 3}


def mint(kind: str, **parts: object) -> str:
    """`doctor://{kind}/{part...}` — deterministic, order-stable.

    Parts serialize in canonical order (id, subject, i, digest; unknown
    names last, sorted) so `mint(kind, a=1, b=2)` always yields the
    same ref regardless of kwarg order.
    """
    if kind not in REF_KINDS:
        raise ContextRefError(f"unknown context ref kind: {kind}")
    keys = sorted(parts, key=lambda k: (_PART_ORDER.get(k, 99), k))
    segments = [_norm(parts[k]) for k in keys]
    if any(not s for s in segments):
        raise ContextRefError("empty ref part")
    uri = f"{CONTEXT_REF_PREFIX}{kind}"
    if segments:
        uri += "/" + "/".join(segments)
    return uri


def parse(uri: str) -> ContextRef:
    """Strict `doctor://` parse — unknown kinds are errors."""
    if not uri.startswith(CONTEXT_REF_PREFIX):
        raise ContextRefError(f"not a context ref: {uri!r}")
    body = uri[len(CONTEXT_REF_PREFIX):]
    segments = [s for s in body.split("/") if s]
    if not segments:
        raise ContextRefError("missing ref kind")
    kind, parts = segments[0], tuple(segments[1:])
    if kind not in REF_KINDS:
        raise ContextRefError(f"unknown context ref kind: {kind}")
    return ContextRef(kind=kind, parts=parts)


def content_digest(text: str) -> str:
    """Stable short digest for content-addressed refs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _finding_ref(f: Finding) -> str:
    # entity_ids are optional on a Finding; fall back to the first
    # evidence source so every finding gets a mintable ref.
    subject = (f.entity_ids[0] if f.entity_ids
               else (f.evidence[0].source if f.evidence else "report"))
    return mint("finding", id=f.id, subject=subject,
                digest=content_digest(
                    f"{f.id}|{subject}|{f.description}"))


def finding_refs(report: DoctorReport) -> tuple[str, ...]:
    return tuple(_finding_ref(f) for f in report.findings)


def context_slice(report: DoctorReport, ref: str) -> ContextSlice:
    """Bounded minimal view of `report` for `ref`.

    Kinds not present in the report return an empty slice — absence is
    data, and the caller can still see the ref parsed correctly.
    """
    parsed = parse(ref)
    kind = parsed.kind

    if kind == "finding":
        for f in report.findings:
            if _finding_ref(f) == ref:
                return ContextSlice(
                    ref=ref, kind=kind, findings=(f,),
                    unknowns=f.unknowns)
        return ContextSlice(ref=ref, kind=kind)

    if kind == "unknown":
        idx = int(parsed.parts[0]) if parsed.parts else 0
        unknowns = report.unknowns[idx: idx + 1]
        return ContextSlice(ref=ref, kind=kind, unknowns=unknowns)

    if kind == "service":
        truncated = len(report.operations) > MAX_OPS_PER_SLICE
        ops = report.operations[:MAX_OPS_PER_SLICE]
        findings = tuple(sorted(
            {f.id for f in report.findings}))[:MAX_FINDINGS_PER_SLICE]
        fields = (
            ("project", report.project or ""),
            ("operations", json.dumps(ops)),
            ("finding_ids", json.dumps(list(findings))),
        )
        return ContextSlice(
            ref=ref, kind=kind, fields=fields, truncated=truncated)

    if kind == "operation":
        ident = "/".join(parsed.parts)
        related = tuple(
            f for f in report.findings
            if ident in f.entity_ids or any(
                ident in e for e in f.entity_ids)
        )[:MAX_FINDINGS_PER_SLICE]
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(("operation", ident),),
            findings=related,
            truncated=len(related) == MAX_FINDINGS_PER_SLICE)

    if kind == "graph":
        summary = report.graph
        if summary is None:
            return ContextSlice(ref=ref, kind=kind)
        if parsed.parts:
            # doctor://graph/{entity-id} — bounded depth-1 slice of the
            # flat edge export (spec 057), evidence refs preserved.
            root = "/".join(parsed.parts)
            edges = tuple(
                e for e in report.graph_edges
                if e.from_id == root or e.to_id == root
            )[:MAX_GRAPH_EDGES]
            return ContextSlice(
                ref=ref, kind=kind,
                fields=(
                    ("root", root),
                    ("edges", json.dumps(
                        [e.to_dict() for e in edges], sort_keys=True)),
                ),
                truncated=len(report.graph_edges) > MAX_GRAPH_EDGES
                and len(edges) == MAX_GRAPH_EDGES)
        ids = summary.ids[:MAX_GRAPH_EDGES]
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(
                ("entities", json.dumps(
                    dict(summary.counts), sort_keys=True)),
                ("service_ids", json.dumps(list(ids))),
            ),
            truncated=len(summary.ids) > MAX_GRAPH_EDGES)

    if kind == "runtime":
        summary = report.runtime
        if summary is None:
            return ContextSlice(ref=ref, kind=kind)
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(("counts", json.dumps(
                dict(summary.counts), sort_keys=True)),))

    if kind == "contract":
        summary = report.contracts
        if summary is None:
            return ContextSlice(ref=ref, kind=kind)
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(("counts", json.dumps(
                dict(summary.counts), sort_keys=True)),))

    if kind == "capability":
        caps = report.capabilities[:MAX_CAPABILITIES]
        names = tuple(c.capability.value for c in caps)
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(("capabilities", json.dumps(list(names))),),
            truncated=len(report.capabilities) > MAX_CAPABILITIES)

    if kind == "handoff":
        return ContextSlice(
            ref=ref, kind=kind,
            fields=(
                ("schema_version", report.schema_version),
                ("analysis_rev", report.analysis_rev or ""),
            ))

    return ContextSlice(ref=ref, kind=kind)  # unreachable: kinds gated


def measure(report: DoctorReport) -> ContextMetrics:
    """§35 token economy for this report (documented heuristics)."""
    raw = report.to_json().encode("utf-8")
    svc = context_slice(report, mint("service"))
    slice_bytes = len(svc.to_json().encode("utf-8"))
    evidence_refs = sum(len(f.evidence) for f in report.findings)
    return ContextMetrics(
        raw_bytes=len(raw),
        slice_bytes=slice_bytes,
        estimated_tokens=max(1, len(raw) // _CHARS_PER_TOKEN),
        evidence_refs=evidence_refs,
        unknowns=len(report.unknowns),
    )
