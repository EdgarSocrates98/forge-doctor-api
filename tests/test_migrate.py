"""Spec 028 - migration intelligence (§77-§83, §167).

Analysis only; classifications must reflect full dimension coverage, with
UNKNOWN preferred over optimistic classes.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.migrate import (
    DecisionQuestion,
    MigrationClass,
    MigrationKind,
    assess_contract_version,
    assess_gateway_to_gateway,
    assess_rest_to_graphql,
    assess_rest_to_grpc,
    assess_sync_to_async,
    assess_version_upgrade,
    decide,
)
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security.scan import load_security_model

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0.0"}
paths:
  /items/{id}:
    get:
      operationId: getItem
      parameters:
        - {name: id, in: path, required: true, schema: {type: string}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties: {id: {type: string}}
        "404": {description: missing}
    post:
      operationId: createItem
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties: {name: {type: string}}
      responses:
        "201": {description: created}
"""

OPENAPI_STREAMED = """\
openapi: 3.0.3
info: {title: T, version: "1.0.0"}
paths:
  /events:
    get:
      operationId: streamEvents
      responses:
        "200":
          description: stream
          content:
            text/event-stream:
              schema: {type: object}
"""

OPENAPI_WEBHOOKS = """\
openapi: 3.1.0
info: {title: T, version: "1.0.0"}
paths: {}
webhooks:
  itemUpdated:
    post:
      responses:
        "200": {description: ok}
components:
  schemas:
    Item:
      type: [object, "null"]
      properties: {id: {type: string}}
"""

ASYNCAPI = """\
asyncapi: "2.6.0"
info: {title: E, version: "1.0.0"}
channels:
  items:
    publish:
      message:
        name: ItemEvent
        correlationId: {location: $message.header#/correlation}
        payload: {type: object}
    bindings:
      amqp:
        x-dlq: items-dlq
        x-ordering: partition-key
        x-delivery: at-least-once
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _api(tmp_path: Path, doc: str = OPENAPI, name: str = "p"):
    root = _write(tmp_path / name, {"api.yaml": doc})
    ctx = ProjectContext.from_root(root)
    return ctx, load_openapi_project(ctx)


# --- §79 REST -> gRPC ----------------------------------------------------------


def test_rest_to_grpc_full_dimension_coverage(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_rest_to_grpc(api)
    assert m.kind is MigrationKind.REST_TO_GRPC
    assert {a.subject for a in m.assessments} == {
        "operation_id:getItem", "operation_id:createItem",
    }
    for a in m.assessments:
        dims = {d.dimension for d in a.dimensions}
        assert dims == {
            "request/response", "status semantics", "streaming",
            "metadata/headers", "error model", "timeouts", "idempotency",
        }


def test_rest_to_grpc_idempotent_method_direct(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_rest_to_grpc(api)
    get = next(a for a in m.assessments if "getItem" in a.subject)
    idem = next(d for d in get.dimensions if d.dimension == "idempotency")
    assert idem.classification is MigrationClass.DIRECT


def test_rest_to_grpc_post_idempotency_unknown(tmp_path: Path) -> None:
    """UNKNOWN over optimistic: POST with no idempotency evidence."""
    _, api = _api(tmp_path)
    m = assess_rest_to_grpc(api)
    post = next(a for a in m.assessments if "createItem" in a.subject)
    idem = next(d for d in post.dimensions if d.dimension == "idempotency")
    assert idem.classification is MigrationClass.UNKNOWN
    assert post.classification is MigrationClass.UNKNOWN
    assert post.unknowns


def test_rest_to_grpc_timeout_evidence_direct(tmp_path: Path) -> None:
    ctx, api = _api(tmp_path)
    _write(tmp_path / "p", {"cfg.yaml": "timeouts: {svc: {timeout: 2000}}\n"})
    rel = load_reliability_model(ctx, ["cfg.yaml"])
    m = assess_rest_to_grpc(api, rel)
    for a in m.assessments:
        t = next(d for d in a.dimensions if d.dimension == "timeouts")
        assert t.classification is MigrationClass.DIRECT
        assert t.evidence


def test_rest_to_grpc_streaming_approximate(tmp_path: Path) -> None:
    _, api = _api(tmp_path, OPENAPI_STREAMED, "s")
    m = assess_rest_to_grpc(api)
    a = m.assessments[0]
    s = next(d for d in a.dimensions if d.dimension == "streaming")
    assert s.classification is MigrationClass.APPROXIMATE


def test_rest_to_grpc_empty_project_unknown(tmp_path: Path) -> None:
    root = _write(tmp_path / "empty", {"x.txt": "nothing\n"})
    api = load_openapi_project(ProjectContext.from_root(root))
    m = assess_rest_to_grpc(api)
    assert m.assessments == () and m.unknowns


# --- §80 REST -> GraphQL --------------------------------------------------------


def test_rest_to_graphql_always_redesign(tmp_path: Path) -> None:
    """§80: never endpoint->field auto-mapping; reasons in dimension terms."""
    _, api = _api(tmp_path)
    m = assess_rest_to_graphql(api)
    for a in m.assessments:
        assert a.classification is MigrationClass.REDESIGN_REQUIRED
        assert all(d.classification is MigrationClass.REDESIGN_REQUIRED
                   for d in a.dimensions)
        assert all(d.detail for d in a.dimensions)


# --- §81 sync -> async -----------------------------------------------------------


def test_sync_to_async_full_coverage(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_sync_to_async(api)
    for a in m.assessments:
        assert {d.dimension for d in a.dimensions} == {
            "request-response", "delivery semantics", "correlation",
            "retry", "dlq", "ordering", "event schema",
        }


def test_sync_to_async_no_asyncapi_all_unknown(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_sync_to_async(api, asyncapi=None)
    a = m.assessments[0]
    # every evidence-dependent dimension stays UNKNOWN without an
    # AsyncAPI document; request-response is a proven redesign blocker.
    for d in a.dimensions:
        if d.dimension != "request-response":
            assert d.classification is MigrationClass.UNKNOWN
    assert a.unknowns


def test_sync_to_async_with_evidence(tmp_path: Path) -> None:
    ctx, api = _api(tmp_path)
    _write(tmp_path / "p", {"async.yaml": ASYNCAPI})
    am = load_asyncapi_project(ctx)
    m = assess_sync_to_async(api, am)
    a = m.assessments[0]
    corr = next(d for d in a.dimensions if d.dimension == "correlation")
    assert corr.classification is MigrationClass.DIRECT


# --- §77 gateway -> gateway ------------------------------------------------------


def test_gateway_to_gateway_known_target(tmp_path: Path) -> None:
    root = _write(tmp_path / "gw", {
        "gw.yaml": (
            "rate_limit: {scope: edge, limit: 100}\n"
            "cors: {scope: edge, allow_origins: [https://a.com]}\n"
        ),
    })
    ctx = ProjectContext.from_root(root)
    sec = load_security_model(ctx, ["gw.yaml"])
    m = assess_gateway_to_gateway("aws-api-gateway", "kong", sec)
    assert m.assessments
    a = m.assessments[0]
    by_dim = {d.dimension: d.classification for d in a.dimensions}
    assert by_dim["rate-limiting"] is MigrationClass.DIRECT
    assert by_dim["cors"] is MigrationClass.DIRECT


def test_gateway_to_gateway_missing_capability(tmp_path: Path) -> None:
    """Capability observed but absent from the target pack -> NO_EQUIVALENT."""
    root = _write(tmp_path / "gw2", {
        "gw.yaml": "rate_limit: {scope: edge, limit: 10}\n",
    })
    ctx = ProjectContext.from_root(root)
    sec = load_security_model(ctx, ["gw.yaml"])
    m = assess_gateway_to_gateway("kong", "nginx", sec)
    a = m.assessments[0]
    rl = next(d for d in a.dimensions if d.dimension == "rate-limiting")
    assert rl.classification is MigrationClass.DIRECT  # nginx has rate-limiting
    m2 = assess_gateway_to_gateway("kong", "aws-api-gateway", sec)
    rl2 = next(d for d in m2.assessments[0].dimensions
               if d.dimension == "rate-limiting")
    assert rl2.classification is MigrationClass.DIRECT  # throttling alias


def test_gateway_unknown_platform(tmp_path: Path) -> None:
    m = assess_gateway_to_gateway("kong", "nonexistent-gw")
    assert not m.assessments
    assert any("capability pack" in u.missing for u in m.unknowns)


# --- §82 contract version --------------------------------------------------------


def test_contract_version_webhooks_blocked(tmp_path: Path) -> None:
    _, api = _api(tmp_path, OPENAPI_WEBHOOKS, "w")
    m = assess_contract_version(api, "3.0")
    a = m.assessments[0]
    assert a.classification is MigrationClass.NO_EQUIVALENT
    wh = next(d for d in a.dimensions if d.dimension == "webhooks")
    assert wh.classification is MigrationClass.NO_EQUIVALENT


def test_contract_version_nullable_approximate(tmp_path: Path) -> None:
    doc = OPENAPI + (
        "components:\n  schemas:\n"
        "    X: {type: object, nullable: true, "
        "properties: {a: {type: string}}}\n")
    _, api = _api(tmp_path, doc, "n")
    m = assess_contract_version(api, "3.1")
    a = m.assessments[0]
    nu = next(d for d in a.dimensions if d.dimension == "nullable")
    assert nu.classification is MigrationClass.APPROXIMATE


def test_contract_version_clean_contract_direct(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_contract_version(api, "3.1")
    assert m.assessments[0].classification is MigrationClass.DIRECT


# --- §83 client generation impact + v1->v2 --------------------------------------


def test_client_generation_impact_flags_structural(tmp_path: Path) -> None:
    before_root = _write(tmp_path / "b", {"api.yaml": OPENAPI})
    after = OPENAPI.replace(
        "      parameters:\n"
        "        - {name: id, in: path, required: true, schema: {type: string}}\n",
        "")
    after_root = _write(tmp_path / "a", {"api.yaml": after})
    b = load_openapi_project(ProjectContext.from_root(before_root))
    a = load_openapi_project(ProjectContext.from_root(after_root))
    m = assess_version_upgrade(b, a)
    assert m.sdk_impacts
    assert all(i.affects_sdk for i in m.sdk_impacts)
    assert m.assessments


def test_version_upgrade_removed_endpoint_no_equivalent(tmp_path: Path) -> None:
    after = OPENAPI.split("    post:")[0]
    before_root = _write(tmp_path / "b2", {"api.yaml": OPENAPI})
    after_root = _write(tmp_path / "a2", {"api.yaml": after})
    b = load_openapi_project(ProjectContext.from_root(before_root))
    a = load_openapi_project(ProjectContext.from_root(after_root))
    m = assess_version_upgrade(b, a)
    removed = [x for a_ in m.assessments for d in a_.dimensions
               for x in [d] if d.dimension == "method_removed"
               or d.dimension == "endpoint_removed"]
    assert removed
    assert any(d.classification in {
        MigrationClass.NO_EQUIVALENT, MigrationClass.REDESIGN_REQUIRED}
        for d in removed)


# --- §167 decision briefs --------------------------------------------------------


def test_decide_move_to_grpc_brief(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_rest_to_grpc(api)
    brief = decide(DecisionQuestion.CAN_MOVE_TO_GRPC, "createItem",
                   migration=m)
    assert brief.constraints == ()
    assert brief.tradeoffs  # APPROXIMATE dims
    assert brief.unknowns  # idempotency unknown on POST
    assert not hasattr(brief, "verdict")


def test_decide_retire_version(tmp_path: Path) -> None:
    brief = decide(DecisionQuestion.CAN_RETIRE_VERSION, "v1",
                   remaining_clients=0)
    assert any("no client call sites" in f for f in brief.facts)
    brief2 = decide(DecisionQuestion.CAN_RETIRE_VERSION, "v1",
                    remaining_clients=3)
    assert brief2.constraints
    brief3 = decide(DecisionQuestion.CAN_RETIRE_VERSION, "v1")
    assert brief3.unknowns


def test_assessment_serialization_roundtrip(tmp_path: Path) -> None:
    _, api = _api(tmp_path)
    m = assess_rest_to_grpc(api)
    data = m.to_dict()
    assert data["kind"] == "rest-to-grpc"
    assert data["assessments"]
