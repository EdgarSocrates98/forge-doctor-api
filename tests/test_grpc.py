"""gRPC/proto model + GRPC### check tests (spec 013, §25-27, §44, §157, §185)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.grpc import (
    ProtoDocumentStatus,
    StreamingMode,
    grpc_graph,
    load_grpc_project,
)
from forge_doctor_api.checks.grpc import grpc_breaking_changes, run_grpc_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Confidence

PROTO = '''syntax = "proto3";
package acme.v1;
import "google/protobuf/empty.proto";
import "common.proto";

message User {
  string id = 1;
  string email = 2;
  reserved 3, 5 to 7;
  reserved "legacy";
  oneof contact { string phone = 4; }
}
message GetUserRequest { string id = 1; }
service UserService {
  rpc GetUser(GetUserRequest) returns (User);
  rpc Watch(GetUserRequest) returns (stream User) {
    option idempotency_level = NO_SIDE_EFFECTS;
  }
}
enum Role { ROLE_UNSPECIFIED = 0; ADMIN = 1; }
'''

COMMON = 'syntax = "proto3";\npackage acme.v1;\nmessage Empty {}\n'


def _model(root: Path, files: dict[str, str]):
    for name, text in files.items():
        t = root / name
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
    return load_grpc_project(ProjectContext.from_root(root), list(files))


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# -- parsing ------------------------------------------------------------------


def test_proto_parses(tmp_path: Path) -> None:
    model = _model(tmp_path, {"user.proto": PROTO, "common.proto": COMMON})
    assert model.documents[0].status is ProtoDocumentStatus.PARSED
    svc = model.services[0]
    assert svc.name == "UserService" and svc.package == "acme.v1"
    methods = {m.name: m for m in svc.methods}
    assert methods["GetUser"].streaming is StreamingMode.UNARY
    assert methods["Watch"].streaming is StreamingMode.SERVER_STREAMING
    assert methods["Watch"].idempotent_evidence == ("NO_SIDE_EFFECTS",)
    user = next(m for m in model.messages if m.name == "User")
    assert user.reserved_numbers == (3, 5, 6, 7)
    assert user.reserved_names == ("legacy",)
    assert user.oneofs == ("contact",)
    assert {f.number for f in user.fields} == {1, 2, 4}


def test_unresolved_import_recorded(tmp_path: Path) -> None:
    model = _model(tmp_path, {"user.proto": PROTO, "common.proto": COMMON})
    f = next(f for f in model.files if f.path == "user.proto")
    assert f.unresolved_imports == ("google/protobuf/empty.proto",)
    assert any(i.code.value == "UNRESOLVED_IMPORT" for i in model.issues)


def test_malformed_proto_is_issue(tmp_path: Path) -> None:
    model = _model(tmp_path, {"bad.proto": "syntax = \"proto3\";\nmessage X {\n"})
    assert model.documents[0].status is ProtoDocumentStatus.MALFORMED


def test_comment_embedded_service_not_parsed(tmp_path: Path) -> None:
    proto = (
        'syntax = "proto3";\n'
        "// service Fake { rpc X(A) returns (B); }\n"
        "/* service Also { rpc Y(A) returns (B); } */\n"
        "message A { string x = 1; }\n"
    )
    model = _model(tmp_path, {"a.proto": proto})
    assert model.services == ()


def test_single_line_blocks(tmp_path: Path) -> None:
    proto = 'syntax = "proto3";\nenum E { A = 0; B = 1; }\nmessage M { string x = 1; }\n'
    model = _model(tmp_path, {"a.proto": proto})
    assert model.enums[0].values == {"A": 0, "B": 1}
    assert model.messages[0].fields[0].name == "x"


# -- graph ---------------------------------------------------------------------


def test_graph_entities(tmp_path: Path) -> None:
    model = _model(tmp_path, {"user.proto": PROTO, "common.proto": COMMON})
    g = grpc_graph(model)
    kinds = {e.kind for e in g.entities()}
    assert {"grpc_service", "grpc_method", "proto_message"} <= kinds
    rels = {r.kind for r in g.relationships()}
    assert {"EXPOSES", "ACCEPTS", "RETURNS"} <= rels


# -- single-model checks ---------------------------------------------------------


def test_grpc001_no_deadline_evidence(tmp_path: Path) -> None:
    model = _model(tmp_path, {"user.proto": PROTO, "common.proto": COMMON})
    assert "GRPC001" in _ids(run_grpc_checks(model))


def test_grpc001_clean_with_stub_deadline(tmp_path: Path) -> None:
    files = {
        "user.proto": PROTO,
        "c.py": "s = UserServiceStub(ch)\ns.GetUser(r, timeout=5)\n",
    }
    model = _model(tmp_path, files)
    assert "GRPC001" not in _ids(run_grpc_checks(model))


def test_grpc002_retry_without_idempotency(tmp_path: Path) -> None:
    files = {
        "user.proto": PROTO,
        "cfg.yaml": "methodConfig:\n  - retryPolicy: {maxAttempts: 3}\n",
    }
    model = _model(tmp_path, files)
    f = next(f for f in run_grpc_checks(model) if f.id == "GRPC002")
    assert f.confidence is Confidence.LOW and f.unknowns
    assert "GetUser" in f.description  # Watch is idempotent, excluded


def test_grpc004_reserved_overlap(tmp_path: Path) -> None:
    proto = (
        'syntax = "proto3";\n'
        "message M { string a = 1; reserved 1; }\n"
    )
    model = _model(tmp_path, {"a.proto": proto})
    assert "GRPC004" in _ids(run_grpc_checks(model))


def test_grpc005_prod_config_without_health(tmp_path: Path) -> None:
    files = {
        "user.proto": PROTO,
        "grpc-prod.yaml": "env: production\nloadBalancingPolicy: round_robin\n",
    }
    model = _model(tmp_path, files)
    assert "GRPC005" in _ids(run_grpc_checks(model))


def test_grpc005_clean_with_health(tmp_path: Path) -> None:
    files = {
        "user.proto": PROTO,
        "prod.yaml": "env: production\nhealthCheckConfig: {serviceName: ''}\n",
    }
    model = _model(tmp_path, files)
    assert "GRPC005" not in _ids(run_grpc_checks(model))


def test_grpc007_retry_amplification(tmp_path: Path) -> None:
    files = {
        "user.proto": PROTO,
        "cfg.yaml": "retryPolicy: {maxAttempts: 5}\n",
    }
    model = _model(tmp_path, files)
    f = next(f for f in run_grpc_checks(model) if f.id == "GRPC007")
    assert f.confidence is Confidence.LOW and f.unknowns


# -- diff checks (§26) -------------------------------------------------------------

OLD = '''syntax = "proto3";
package acme.v1;
message M { string id = 1; string email = 2; int32 n = 3; }
service S { rpc Get(M) returns (M); rpc List(M) returns (stream M); }
enum R { A = 0; B = 1; }
'''


def test_grpc003_removed_without_reserved(tmp_path: Path) -> None:
    new = OLD.replace(" string email = 2;", "")
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    assert "GRPC003" in _ids(d.findings)


def test_grpc004_number_reuse(tmp_path: Path) -> None:
    new = OLD.replace("string id = 1;", "string uuid = 1;")
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    assert "GRPC004" in _ids(d.findings)


def test_grpc004_clean_when_renamed_field_reserved(tmp_path: Path) -> None:
    """Removing + reserving + new field at a different number = no reuse."""
    new = OLD.replace(
        "message M { string id = 1; string email = 2; int32 n = 3; }",
        "message M { string id = 1; int32 n = 3; reserved 2; string name = 4; }",
    )
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    assert "GRPC004" not in _ids(d.findings)


def test_grpc006_streaming_change(tmp_path: Path) -> None:
    new = OLD.replace(
        "rpc Get(M) returns (M);", "rpc Get(M) returns (stream M);"
    )
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    assert "GRPC006" in _ids(d.findings)


def test_incompatible_type_change_classified(tmp_path: Path) -> None:
    new = OLD.replace("int32 n = 3;", "string n = 3;")
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    kinds = {(c.kind, c.classification.value) for c in d.changes}
    assert ("GRPC_TYPE_CHANGED", "BREAKING") in kinds


def test_wire_compatible_type_change_is_candidate(tmp_path: Path) -> None:
    new = OLD.replace("int32 n = 3;", "int64 n = 3;")
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    kinds = {(c.kind, c.classification.value) for c in d.changes}
    assert ("GRPC_TYPE_CHANGED", "POTENTIALLY_BREAKING") in kinds


def test_removed_method_and_enum(tmp_path: Path) -> None:
    new = OLD.replace("rpc List(M) returns (stream M);", "").replace(
        "enum R { A = 0; B = 1; }", "enum R { A = 0; }"
    )
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    kinds = {c.kind for c in d.changes}
    assert "GRPC_METHOD_REMOVED" in kinds
    assert "GRPC_ENUM_REMOVED" in kinds


def test_package_rename(tmp_path: Path) -> None:
    new = OLD.replace("package acme.v1;", "package acme.v2;")
    old = _model(tmp_path / "o", {"a.proto": OLD})
    new_m = _model(tmp_path / "n", {"a.proto": new})
    d = grpc_breaking_changes(old, new_m)
    kinds = {c.kind for c in d.changes}
    assert "GRPC_RENAME" in kinds


# -- determinism --------------------------------------------------------------------


def test_determinism(tmp_path: Path) -> None:
    files = {"a.proto": PROTO, "b.proto": COMMON}
    one = _model(tmp_path / "x", files)
    two = _model(tmp_path / "y", files)
    assert one.to_dict() == two.to_dict()
    a, b = run_grpc_checks(one), run_grpc_checks(two)
    assert [f.to_dict() for f in a] == [f.to_dict() for f in b]
