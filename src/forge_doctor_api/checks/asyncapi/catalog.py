"""ASYNC### check catalog (§21, §218)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Confidence, EvidenceKind, Severity


@dataclass(frozen=True)
class AsyncCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    trigger: str


CATALOG: tuple[AsyncCheckSpec, ...] = (
    AsyncCheckSpec("ASYNC001", "Channel without message schema", Severity.MEDIUM,
                   Confidence.HIGH, EvidenceKind.STATIC,
                   "A channel declares no resolvable payload-bearing message."),
    AsyncCheckSpec("ASYNC002", "Message missing correlation id", Severity.LOW,
                   Confidence.HIGH, EvidenceKind.STATIC,
                   "A message has no `correlationId.location` evidence."),
    AsyncCheckSpec("ASYNC003", "Producer/consumer schema drift", Severity.HIGH,
                   Confidence.HIGH, EvidenceKind.STATIC,
                   "Send-side and receive-side payload schemas on one channel "
                   "differ semantically (via the unified schema diff, §121)."),
    AsyncCheckSpec("ASYNC004", "Retry without DLQ evidence", Severity.MEDIUM,
                   Confidence.LOW, EvidenceKind.STATIC,
                   "Retry markers exist without dead-letter evidence. "
                   "Candidate — delivery semantics may live outside the doc."),
    AsyncCheckSpec("ASYNC005", "Unordered processing assumption", Severity.MEDIUM,
                   Confidence.LOW, EvidenceKind.STATIC,
                   "A kafka-bound channel lacks partitioning/ordering evidence."),
    AsyncCheckSpec("ASYNC006", "Incompatible message evolution", Severity.HIGH,
                   Confidence.MEDIUM, EvidenceKind.STATIC,
                   "Same-named messages carry semantically different payloads."),
    AsyncCheckSpec("ASYNC007", "Missing consumer ownership", Severity.MEDIUM,
                   Confidence.LOW, EvidenceKind.STATIC,
                   "A channel is published to but declares no consumer. "
                   "Candidate — consumers may live in other services."),
    AsyncCheckSpec("ASYNC008", "Operation without delivery semantics", Severity.LOW,
                   Confidence.LOW, EvidenceKind.STATIC,
                   "No binding/marker evidence of delivery guarantees "
                   "(acks, qos, delivery mode). Candidate."),
)

BY_ID: dict[str, AsyncCheckSpec] = {spec.id: spec for spec in CATALOG}
