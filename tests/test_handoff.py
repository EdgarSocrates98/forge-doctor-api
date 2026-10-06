"""Spec 029 - handoff & integration (§133-§138, §167, §215).

Bundles are compact references + summaries (§135); routing declares
destinations without executing; cross-domain is references only (§138).
"""

from __future__ import annotations

import json
from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
)
from forge_doctor_api.handoff import (
    DoctorApi,
    ExternalReference,
    ForgerRequest,
    answer_become_async,
    answer_enable_retry_safely,
    answer_move_to_grpc,
    answer_retire_version,
    assemble_bundle,
    route_request,
)
from forge_doctor_api.knowledge import detect_capabilities
from forge_doctor_api.migrate import DecisionQuestion

OPENAPI = """\
openapi: 3.0.3
info: {title: Payments, version: "1.2.0"}
paths:
  /charges/{id}:
    get:
      operationId: getCharge
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
      responses:
        "200": {description: ok}
"""

OPENAPI_V2 = """\
openapi: 3.0.3
info: {title: Payments, version: "2.0.0"}
paths:
  /charges/{id}:
    get:
      operationId: getCharge
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
      responses:
        "200": {description: ok}
  /refunds:
    post:
      operationId: createRefund
      responses:
        "201": {description: created}
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _finding(**kw) -> Finding:
    values = {
        "id": "APISEC001",
        "title": "t",
        "description": "d",
        "severity": Severity.MEDIUM,
        "confidence": Confidence.HIGH,
        "evidence_kind": EvidenceKind.STATIC,
        "evidence": (Evidence(kind=EvidenceKind.STATIC,
                              source="api.yaml", summary="e"),),
    }
    values.update(kw)
    return Finding(**values)


# --- §134/§135 bundle ----------------------------------------------------------


def test_bundle_compact_and_versioned(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": OPENAPI})
    api = load_openapi_project(ProjectContext.from_root(root))
    b = assemble_bundle(service="payments", openapi=api,
                        findings=(_finding(),))
    assert b.schema_version
    assert b.operations == ("GET /charges/{id}",)
    assert b.contracts == ("api.yaml openapi=3.0.3",)
    assert b.security_candidates and "APISEC001" in b.security_candidates[0]
    assert b.remediation_candidates
    assert b.knowledge_versions["openapi-versions"]
    payload = json.dumps(b.to_dict())
    assert "type: object" not in payload  # no schema payloads shipped


def test_bundle_unknowns_present(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": OPENAPI})
    api = load_openapi_project(ProjectContext.from_root(root))
    from forge_doctor_api.core.models import UnknownFact
    b = assemble_bundle(
        openapi=api,
        unknowns=(UnknownFact(subject="x", missing="runtime evidence",
                              resolution="ship OTLP"),))
    assert any(u.missing == "runtime evidence" for u in b.unknowns)


def test_bundle_redaction(tmp_path: Path) -> None:
    """§135: secrets never reach the serialized bundle."""
    root = _write(tmp_path / "p", {"api.yaml": OPENAPI})
    api = load_openapi_project(ProjectContext.from_root(root))
    secret = "sk-live-abcdef0123456789"
    b = assemble_bundle(openapi=api, findings=(_finding(
        description=f"token {secret} exposed"),))
    assert secret not in json.dumps(b.to_dict())


# --- §138 external references ----------------------------------------------------


def test_external_reference_is_reference_only() -> None:
    ref = ExternalReference(
        source_id="operation:api:getCharge",
        target_domain="data",
        target_ref="db:orders",
        relation="downstream-dependency",
    )
    assert ref.target_domain == "data"
    d = ref.to_dict()
    assert "graph" not in d  # no merged-graph surface exists


# --- §136/§215 routing -----------------------------------------------------------


def test_forger_routes_api_domain() -> None:
    r = route_request(ForgerRequest(task="my endpoint is slow"))
    assert r.handler == "api-forge"
    assert r.chain == ("doctor-api", "api-forge")


def test_forger_routes_data_dependency() -> None:
    refs = (ExternalReference(
        source_id="op:x", target_domain="data", target_ref="db:t",
        relation="downstream"),)
    r = route_request(ForgerRequest(task="slow endpoint"), refs)
    assert r.handler == "data-doctor"
    assert "data-doctor" in r.chain
    impl = route_request(
        ForgerRequest(task="slow endpoint; implement backfill"), refs)
    assert impl.chain[-1] == "spark-forge"


def test_forger_unknown_domain_declared() -> None:
    r = route_request(ForgerRequest(task="x", domain="billing"))
    assert r.handler == "unrouted"
    assert r.unknowns


# --- §133 MCP surface (local invocation) -----------------------------------------


def test_mcp_surface_local(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": OPENAPI})
    api = DoctorApi(ProjectContext.from_root(root))
    assert api.get_service()["operations"] == 1
    assert api.get_api()["operations"][0]["method"].lower() == "get"
    assert api.get_operation("getCharge")["path"] == "/charges/{id}"
    assert api.get_operation("missing") is None
    assert api.get_contract()["documents"][0]["openapi_version"] == "3.0.3"
    assert isinstance(api.get_clients(), dict)
    assert isinstance(api.get_reliability_status(), dict)
    assert isinstance(api.get_security_findings(), dict)
    assert isinstance(api.get_unknowns()["unknowns"], list)
    # payload serializable for future transport
    json.dumps(api.get_service())


def test_mcp_breaking_changes_without_before(tmp_path: Path) -> None:
    api = DoctorApi(ProjectContext.from_root(
        _write(tmp_path / "p", {"api.yaml": OPENAPI})))
    assert api.get_breaking_changes() is None
    assert api.get_blast_radius() is None


def test_mcp_breaking_changes_with_before(tmp_path: Path) -> None:
    before_root = _write(tmp_path / "b", {"api.yaml": OPENAPI})
    after_root = _write(tmp_path / "a", {"api.yaml": OPENAPI_V2})
    api = DoctorApi(
        ProjectContext.from_root(after_root),
        before=ProjectContext.from_root(before_root),
    )
    out = api.get_breaking_changes()
    assert out is not None and out["breaking"] == []
    blast = api.get_blast_radius()
    assert blast is not None


# --- §167 decision answers -------------------------------------------------------


def test_answer_move_to_grpc(tmp_path: Path) -> None:
    _, api = None, load_openapi_project(
        ProjectContext.from_root(_write(tmp_path / "p",
                                        {"api.yaml": OPENAPI})))
    brief = answer_move_to_grpc("getCharge", api)
    assert brief.question == DecisionQuestion.CAN_MOVE_TO_GRPC.value
    assert brief.facts or brief.tradeoffs or brief.constraints
    assert not hasattr(brief, "verdict")


def test_answer_retire_version() -> None:
    brief = answer_retire_version("v1", remaining_clients=0,
                                observed_traffic=0)
    assert any("no client call sites" in f for f in brief.facts)
    assert any("observed traffic" in f for f in brief.facts)


def test_answer_become_async(tmp_path: Path) -> None:
    api = load_openapi_project(
        ProjectContext.from_root(_write(tmp_path / "p",
                                        {"api.yaml": OPENAPI})))
    brief = answer_become_async("getCharge", openapi=api)
    assert brief.question == DecisionQuestion.CAN_BECOME_ASYNC.value
    assert brief.unknowns  # no AsyncAPI evidence present


def test_answer_retry_safely(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "cfg.yaml": "retries: [{scope: gw, max_attempts: 3}]\n",
    })
    from forge_doctor_api.reliability import load_reliability_model
    rel = load_reliability_model(
        ProjectContext.from_root(root), ["cfg.yaml"])
    caps = detect_capabilities(reliability=rel)
    brief = answer_enable_retry_safely("gw", caps)
    assert any("SAFE_RETRY" in c or "idempot" in c.lower()
               for c in brief.constraints)


# --- determinism ------------------------------------------------------------------


def test_bundle_deterministic(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {"api.yaml": OPENAPI})
    api = load_openapi_project(ProjectContext.from_root(root))
    b1 = assemble_bundle(openapi=api, findings=(_finding(),))
    b2 = assemble_bundle(openapi=api, findings=(_finding(),))
    assert b1.to_dict() == b2.to_dict()
