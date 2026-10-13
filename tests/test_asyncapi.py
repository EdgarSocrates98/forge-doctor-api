"""AsyncAPI model + ASYNC### check tests (spec 011, §20, §21, §20.2)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.asyncapi import (
    AsyncAction,
    AsyncDocumentStatus,
    async_graph,
    load_asyncapi_project,
)
from forge_doctor_api.checks.asyncapi import run_async_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import RelationshipKind

ASYNC2 = """asyncapi: "2.6.0"
info: {title: Events, version: "1.0"}
servers:
  prod: {host: broker.internal:9092, protocol: kafka}
channels:
  user/signedup:
    bindings: {kafka: {partitions: 3}}
    publish:
      operationId: publishUserSignedUp
      message: {$ref: '#/components/messages/UserSignedUp'}
    subscribe:
      operationId: consumeUserSignedUp
      message: {$ref: '#/components/messages/UserSignedUp'}
components:
  messages:
    UserSignedUp:
      correlationId: {location: "$message.header#/correlation"}
      payload: {$ref: '#/components/schemas/UserEvent'}
      bindings: {kafka: {key: {type: string}}}
  schemas:
    UserEvent:
      type: object
      properties:
        id: {type: string}
        email: {type: string}
"""

ASYNC3 = """asyncapi: "3.1.0"
info: {title: Events, version: "1.0"}
channels:
  userSignedup:
    address: user/signedup
    messages:
      UserSignedUp: {$ref: '#/components/messages/UserSignedUp'}
operations:
  sendUserSignedup:
    action: send
    channel: {$ref: '#/channels/userSignedup'}
  recvUserSignedup:
    action: receive
    channel: {$ref: '#/channels/userSignedup'}
components:
  messages:
    UserSignedUp:
      correlationId: {location: "$message.payload#/cid"}
      payload: {$ref: '#/components/schemas/UserEvent'}
  schemas:
    UserEvent:
      type: object
      properties:
        id: {type: string}
"""


def _model(root: Path, files: dict[str, str]):
    for name, text in files.items():
        t = root / name
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
    return load_asyncapi_project(ProjectContext.from_root(root), list(files))


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# -- model + detection -------------------------------------------------------------


def test_async2_parses(tmp_path: Path) -> None:
    model = _model(tmp_path, {"a.yaml": ASYNC2})
    assert model.documents[0].status is AsyncDocumentStatus.PARSED
    assert model.documents[0].version_family == "2.6"
    assert len(model.channels) == 1
    actions = {o.action for o in model.operations}
    assert actions == {AsyncAction.SEND, AsyncAction.RECEIVE}
    assert model.servers[0].protocol == "kafka"
    assert model.messages[0].correlation_id_location == "$message.header#/correlation"


def test_async3_parses_normalized(tmp_path: Path) -> None:
    model = _model(tmp_path, {"a.yaml": ASYNC3})
    assert model.documents[0].version_family == "3.1"
    actions = {o.action for o in model.operations}
    assert actions == {AsyncAction.SEND, AsyncAction.RECEIVE}
    assert model.channels[0].address == "user/signedup"


def test_strong_marker_required(tmp_path: Path) -> None:
    not_async = "info: {title: X}\nchannels: {a: {}}\n"
    model = _model(tmp_path, {"a.yaml": not_async})
    assert model.channels == ()
    assert any(i.code.value == "NOT_ASYNCAPI" for i in model.issues)


def test_malformed_and_unsupported(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        {"bad.yaml": "asyncapi: [broken", "old.yaml": 'asyncapi: "1.9.0"'},
    )
    statuses = {d.status for d in model.documents}
    assert AsyncDocumentStatus.MALFORMED in statuses
    assert AsyncDocumentStatus.UNSUPPORTED_VERSION in statuses


# -- graph (§20.2) ------------------------------------------------------------------


def test_graph_edges(tmp_path: Path) -> None:
    model = _model(tmp_path, {"a.yaml": ASYNC3})
    graph = async_graph(model, "svc")
    kinds = {r.kind for r in graph.relationships()}
    assert RelationshipKind.PUBLISHES in kinds
    assert RelationshipKind.SUBSCRIBES in kinds
    assert RelationshipKind.PRODUCES in kinds or RelationshipKind.CONSUMES in kinds
    assert any(e.kind == "async_channel" for e in graph.entities())
    assert any(e.kind == "message" for e in graph.entities())


# -- checks ------------------------------------------------------------------------


def test_async001_channel_without_message_schema(tmp_path: Path) -> None:
    spec = """asyncapi: "2.6.0"
info: {title: E, version: "1"}
channels:
  empty/topic:
    publish:
      message: {}
"""
    model = _model(tmp_path, {"a.yaml": spec})
    assert "ASYNC001" in _ids(run_async_checks(model))


def test_async001_clean_when_schema_present(tmp_path: Path) -> None:
    model = _model(tmp_path, {"a.yaml": ASYNC2})
    assert "ASYNC001" not in _ids(run_async_checks(model))


def test_async002_missing_correlation_id(tmp_path: Path) -> None:
    spec = ASYNC2.replace(
        "      correlationId: {location: \"$message.header#/correlation\"}\n", ""
    )
    model = _model(tmp_path, {"a.yaml": spec})
    assert "ASYNC002" in _ids(run_async_checks(model))


def test_async003_producer_consumer_drift(tmp_path: Path) -> None:
    """Publisher and subscriber of one channel disagree on the payload schema."""
    spec = """asyncapi: "2.6.0"
info: {title: E, version: "1"}
channels:
  user/signedup:
    publish:
      message:
        name: PubMsg
        payload:
          type: object
          properties: {id: {type: string}, email: {type: string}}
    subscribe:
      message:
        name: SubMsg
        payload:
          type: object
          properties: {id: {type: integer}}
"""
    model = _model(tmp_path, {"a.yaml": spec})
    assert "ASYNC003" in _ids(run_async_checks(model))


def test_async004_retry_without_dlq(tmp_path: Path) -> None:
    spec = ASYNC2.replace(
        "    bindings: {kafka: {partitions: 3}}",
        "    bindings: {kafka: {partitions: 3}, x-retry: {maxRetries: 5}}",
    )
    model = _model(tmp_path, {"a.yaml": spec})
    findings = run_async_checks(model)
    assert "ASYNC004" in _ids(findings)
    f = next(f for f in findings if f.id == "ASYNC004")
    assert f.unknowns


def test_async004_clean_with_dlq(tmp_path: Path) -> None:
    spec = ASYNC2.replace(
        "    bindings: {kafka: {partitions: 3}}",
        "    bindings: {kafka: {partitions: 3}, x-retry: {}, x-dlq: 'dead'}",
    )
    model = _model(tmp_path, {"a.yaml": spec})
    assert "ASYNC004" not in _ids(run_async_checks(model))


def test_async005_unordered_kafka(tmp_path: Path) -> None:
    spec = ASYNC2.replace(
        "    bindings: {kafka: {partitions: 3}}", "    bindings: {kafka: {}}"
    )
    model = _model(tmp_path, {"a.yaml": spec})
    findings = run_async_checks(model)
    assert "ASYNC005" in _ids(findings)


def test_async006_message_evolution(tmp_path: Path) -> None:
    spec = ASYNC2 + ""
    spec = spec.replace(
        "  schemas:",
        "  messages:\n"
        "    UserSignedUp:\n"
        "      payload:\n"
        "        type: object\n"
        "        properties: {id: {type: integer}}\n"
        "  schemas:",
    )
    # duplicate component name overrides the first in the parsed doc; instead
    # declare the same message name in a second file
    model = _model(
        tmp_path,
        {
            "a.yaml": ASYNC2,
            "b.yaml": """asyncapi: "2.6.0"
info: {title: E2, version: "1"}
channels:
  other/topic:
    publish:
      message: {$ref: '#/components/messages/UserSignedUp'}
components:
  messages:
    UserSignedUp:
      payload: {type: object, properties: {id: {type: integer}}}
""",
        },
    )
    assert "ASYNC006" in _ids(run_async_checks(model))


def test_async007_missing_consumer(tmp_path: Path) -> None:
    spec = """asyncapi: "2.6.0"
info: {title: E, version: "1"}
channels:
  outbound/topic:
    publish:
      message: {payload: {type: object}}
"""
    model = _model(tmp_path, {"a.yaml": spec})
    findings = run_async_checks(model)
    assert "ASYNC007" in _ids(findings)
    assert next(f for f in findings if f.id == "ASYNC007").unknowns


def test_async008_no_delivery_semantics(tmp_path: Path) -> None:
    model = _model(tmp_path, {"a.yaml": ASYNC3})
    assert "ASYNC008" in _ids(run_async_checks(model))


def test_async008_clean_with_delivery_binding(tmp_path: Path) -> None:
    spec = ASYNC3.replace(
        "    channel: {$ref: '#/channels/userSignedup'}\n  recvUserSignedup:",
        "    channel: {$ref: '#/channels/userSignedup'}\n"
        "    bindings: {kafka: {acks: all}}\n  recvUserSignedup:",
    )
    model = _model(tmp_path, {"a.yaml": spec})
    findings = run_async_checks(model)
    send_findings = [
        f for f in findings if f.id == "ASYNC008" and "sendUserSignedup" in f.description
    ]
    assert not send_findings


# -- determinism --------------------------------------------------------------------


def test_determinism(tmp_path: Path) -> None:
    files = {"a.yaml": ASYNC2, "b.yaml": ASYNC3}
    one = _model(tmp_path / "x", files)
    two = _model(tmp_path / "y", files)
    assert [m.to_dict() for m in one.messages] == [m.to_dict() for m in two.messages]
    a, b = run_async_checks(one), run_async_checks(two)
    assert [f.to_dict() for f in a] == [f.to_dict() for f in b]
