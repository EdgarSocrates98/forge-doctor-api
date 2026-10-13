"""§167 decision answers wired to computed outputs — never verdicts."""

from __future__ import annotations

from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.knowledge.capability import (
    CapabilityReport,
)
from forge_doctor_api.migrate import (
    DecisionBrief,
    DecisionQuestion,
    assess_rest_to_grpc,
    assess_sync_to_async,
    decide,
)
from forge_doctor_api.migrate.model import ApiMigrationIntelligence
from forge_doctor_api.reliability.model import ApiReliabilityModel


def answer_move_to_grpc(
    subject: str,
    openapi: OpenApiProjectModel,
    reliability: ApiReliabilityModel | None = None,
    capabilities: CapabilityReport | None = None,
) -> DecisionBrief:
    """§167 'can this move to gRPC' — §79 dimensions as the brief."""
    migration = assess_rest_to_grpc(openapi, reliability)
    return decide(DecisionQuestion.CAN_MOVE_TO_GRPC, subject,
                  migration=migration, capabilities=capabilities)


def answer_become_async(
    subject: str,
    migration: ApiMigrationIntelligence | None = None,
    openapi: OpenApiProjectModel | None = None,
    reliability: ApiReliabilityModel | None = None,
) -> DecisionBrief:
    """§167 'can this become async' — §81 dimensions as the brief."""
    if migration is None and openapi is not None:
        migration = assess_sync_to_async(openapi, reliability=reliability)
    return decide(DecisionQuestion.CAN_BECOME_ASYNC, subject,
                  migration=migration)


def answer_retire_version(
    subject: str,
    remaining_clients: int | None = None,
    observed_traffic: int | None = None,
) -> DecisionBrief:
    """§167 'can v1 be retired' — client evidence + traffic, no verdict."""
    brief = decide(DecisionQuestion.CAN_RETIRE_VERSION, subject,
                   remaining_clients=remaining_clients)
    extra_facts = (
        f"observed traffic count: {observed_traffic}",
    ) if observed_traffic is not None else ()
    return DecisionBrief(
        question=brief.question, subject=brief.subject,
        facts=brief.facts + extra_facts,
        constraints=brief.constraints,
        capabilities=brief.capabilities,
        tradeoffs=brief.tradeoffs,
        unknowns=brief.unknowns,
    )


def answer_enable_retry_safely(
    subject: str,
    capabilities: CapabilityReport,
) -> DecisionBrief:
    """§167 'can retry be enabled safely' — capability gaps as constraints."""
    return decide(DecisionQuestion.CAN_ENABLE_RETRY_SAFELY, subject,
                  capabilities=capabilities)
