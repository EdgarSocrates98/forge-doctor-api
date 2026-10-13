"""Specs 037-038 — artifact discovery, evidence store, analysis plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.discovery import (
    ArtifactClass,
    discover,
)
from forge_doctor_api.core.evidence_store import build_evidence_store
from forge_doctor_api.core.plan import AnalyzerId, build_plan

_OPENAPI = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths: {}
"""

_ASYNCAPI = """\
asyncapi: "2.6.0"
info: {title: E, version: "1.0"}
channels: {}
"""

_K8S = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: x}
"""

_ISTIO = """\
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata: {name: x}
"""

_KONG = """\
_format_version: "3.0"
services: []
"""

_POLICY = """\
policies:
  - id: p1
    rule: require_auth
"""

_OTLP = json.dumps({
    "resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "api"}}]},
        "scopeSpans": [{"scope": {}, "spans": []}],
    }],
})


def _ctx(tmp_path: Path, files: dict[str, str]) -> ProjectContext:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ProjectContext.from_root(tmp_path)


def test_discovery_classifies_every_domain(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "api/openapi.yaml": _OPENAPI,
        "events/asyncapi.yaml": _ASYNCAPI,
        "rpc/service.proto": "syntax = \"proto3\";",
        "schema.graphql": "type Query { x: Int }",
        "infra/main.tf": 'resource "aws_lb" "x" {}',
        "deploy/app.yaml": _K8S,
        "mesh/vs.yaml": _ISTIO,
        "gateway/kong.yaml": _KONG,
        "app/policy.yaml": _POLICY,
        "CODEOWNERS": "* @team",
        "workspace.yaml": "members: []",
        "README.md": "# hi",
        "src/app.py": "x = 1",
        "web/index.ts": "const x = 1",
        "run/otlp.json": _OTLP,
        "misc/thing.bin": "\x00\x01",
    })
    inv = discover(ctx)

    def classes(path: str) -> set[ArtifactClass]:
        a = inv.artifact(path)
        assert a is not None
        return set(a.classes)

    assert ArtifactClass.CONTRACT in classes("api/openapi.yaml")
    assert ArtifactClass.CONTRACT in classes("events/asyncapi.yaml")
    assert ArtifactClass.CONTRACT in classes("rpc/service.proto")
    assert ArtifactClass.CONTRACT in classes("schema.graphql")
    assert ArtifactClass.IAC in classes("infra/main.tf")
    assert ArtifactClass.IAC in classes("deploy/app.yaml")
    assert ArtifactClass.MESH in classes("mesh/vs.yaml")
    assert ArtifactClass.GATEWAY in classes("gateway/kong.yaml")
    assert ArtifactClass.POLICY in classes("app/policy.yaml")
    assert ArtifactClass.OWNERSHIP in classes("CODEOWNERS")
    assert ArtifactClass.WORKSPACE in classes("workspace.yaml")
    assert ArtifactClass.DOCUMENTATION in classes("README.md")
    assert ArtifactClass.SOURCE in classes("src/app.py")
    assert ArtifactClass.CLIENT in classes("src/app.py")
    assert ArtifactClass.CLIENT in classes("web/index.ts")
    assert ArtifactClass.RUNTIME in classes("run/otlp.json")
    assert classes("misc/thing.bin") == {ArtifactClass.UNKNOWN}
    # every yaml/json is CONFIG even when a stronger class applies
    assert ArtifactClass.CONFIG in classes("api/openapi.yaml")


def test_markers_drive_precise_classification(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"api/openapi.yaml": _OPENAPI})
    inv = discover(ctx)
    art = inv.artifact("api/openapi.yaml")
    assert art is not None
    assert "openapi" in art.markers


def test_random_yaml_is_not_a_contract(tmp_path: Path) -> None:
    """Adversarial: a yaml named like a contract but marker-free."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": "service:\n  name: unrelated\n",
        "definitely-not-random.json": '{"hello": "world"}',
    })
    inv = discover(ctx)
    assert ArtifactClass.CONTRACT not in set(
        inv.artifact("openapi.yaml").classes)  # type: ignore[union-attr]
    assert set(inv.artifact("definitely-not-random.json").classes) == {
        ArtifactClass.CONFIG}  # type: ignore[union-attr]


def test_commented_marker_still_enables_not_finds(tmp_path: Path) -> None:
    """Permissive direction: `# openapi:` enables the analyzer, which
    then authoritatively finds nothing — never the reverse."""
    ctx = _ctx(tmp_path, {"x.yaml": "# openapi: 3.0\nfoo: bar\n"})
    inv = discover(ctx)
    assert ArtifactClass.CONTRACT in set(inv.artifact("x.yaml").classes)  # type: ignore[union-attr]


def test_vendored_files_marked_not_dropped(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "node_modules/pkg/index.js": "x",
        ".hidden/secret.yaml": _OPENAPI,
        "src/app.py": "x = 1",
    })
    inv = discover(ctx)
    vendored = inv.artifact("node_modules/pkg/index.js")
    hidden = inv.artifact(".hidden/secret.yaml")
    assert vendored is not None and vendored.vendored
    assert hidden is not None and hidden.vendored
    # vendored excluded from analyzer-facing file lists
    assert "node_modules/pkg/index.js" not in inv.files_in(
        ArtifactClass.SOURCE)
    assert "src/app.py" in inv.files_in(ArtifactClass.SOURCE)


def test_empty_project(tmp_path: Path) -> None:
    inv = discover(ProjectContext.from_root(tmp_path))
    assert inv.artifacts == ()
    assert build_plan(inv).analyzers == ()


def test_discovery_deterministic(tmp_path: Path) -> None:
    files = {"b/x.yaml": _OPENAPI, "a/y.py": "x", "c/z.tf": "r"}
    ctx = _ctx(tmp_path, files)
    assert discover(ctx).to_json() == discover(ctx).to_json()


def test_evidence_store_dedup_and_lookup(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "a/one.yaml": _OPENAPI,
        "b/two.yaml": _OPENAPI,      # identical content -> one entry
        "c/app.py": "x = 1",
    })
    inv = discover(ctx)
    store = build_evidence_store(ctx, inv)
    # dedup: two identical yamls share one hash entry
    assert len(store.entries) == 2
    sha = store.hash_of("a/one.yaml")
    assert sha is not None
    assert set(store.paths_for(sha)) == {"a/one.yaml", "b/two.yaml"}
    assert store.classes_of("c/app.py") == inv.artifact("c/app.py").classes  # type: ignore[union-attr]
    assert store.hash_of("nope") is None


def test_evidence_store_skips_vendored(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"node_modules/x/a.yaml": _OPENAPI, "ok.yaml": _POLICY})
    store = build_evidence_store(ctx, discover(ctx))
    assert store.hash_of("node_modules/x/a.yaml") is None
    assert store.hash_of("ok.yaml") is not None


def test_plan_enables_by_evidence(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "api/openapi.yaml": _OPENAPI,
        "src/app.py": "x = 1",
        "run/otlp.json": _OTLP,
    })
    inv = discover(ctx)
    plan = build_plan(inv)
    assert plan.enabled(AnalyzerId.OPENAPI)
    assert plan.enabled(AnalyzerId.ROUTES)
    assert plan.enabled(AnalyzerId.CLIENTS)
    assert plan.enabled(AnalyzerId.RUNTIME)
    # no evidence for these:
    for a in (AnalyzerId.GRPC, AnalyzerId.GRAPHQL, AnalyzerId.ASYNCAPI,
              AnalyzerId.GATEWAY, AnalyzerId.IAC, AnalyzerId.POLICY):
        assert not plan.enabled(a), a


def test_plan_records_reasons_and_skips(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"x.proto": 'syntax = "proto3";'})
    plan = build_plan(discover(ctx))
    assert plan.enabled(AnalyzerId.GRPC)
    reason = dict(plan.reasons)["grpc"]
    assert "proto" in reason
    skipped = {s.analyzer: s.reason for s in plan.skipped}
    assert skipped[AnalyzerId.OPENAPI] == "no evidence"


def test_plan_force_returns_everything(tmp_path: Path) -> None:
    plan = build_plan(discover(ProjectContext.from_root(tmp_path)),
                      force=True)
    assert len(plan.analyzers) == len(list(AnalyzerId))


def test_plan_deterministic(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {"a.yaml": _K8S, "b.proto": "x", "c.py": "x"})
    inv = discover(ctx)
    assert build_plan(inv).to_json() == build_plan(inv).to_json()


@pytest.mark.parametrize("files,expected", [
    ({"x.yaml": _OPENAPI}, [AnalyzerId.OPENAPI]),
    ({"x.yaml": _ASYNCAPI}, [AnalyzerId.ASYNCAPI]),
    ({"x.graphql": "type Query {x: Int}"}, [AnalyzerId.GRAPHQL]),
    ({"x.proto": "syntax"}, [AnalyzerId.GRPC]),
    ({"x.tf": "resource"}, [AnalyzerId.IAC]),
    ({"x.yaml": _K8S}, [AnalyzerId.IAC]),
    ({"x.yaml": _KONG}, [AnalyzerId.GATEWAY]),
    ({"x.yaml": _ISTIO}, [AnalyzerId.GATEWAY]),  # mesh -> gateway analyzer
    ({"x.yaml": _POLICY}, [AnalyzerId.POLICY]),
    ({"x.json": _OTLP}, [AnalyzerId.RUNTIME]),
    ({"CODEOWNERS": "* @a"}, [AnalyzerId.OWNERSHIP]),
    ({"workspace.yaml": "members: []"}, [AnalyzerId.WORKSPACE]),
])
def test_plan_per_analyzer_rule(
    tmp_path: Path, files: dict[str, str], expected: list[AnalyzerId]
) -> None:
    plan = build_plan(discover(_ctx(tmp_path, files)))
    for a in expected:
        assert plan.enabled(a), a
