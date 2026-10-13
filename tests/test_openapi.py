from __future__ import annotations

import json
import random
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest

from forge_doctor_api.analyzers.openapi import (
    OPENAPI_MODEL_SCHEMA_VERSION,
    CycleKind,
    DocumentStatus,
    IssueCode,
    OpenApiProjectModel,
    OperationSource,
    RefStatus,
    detect_openapi,
    load_openapi_project,
    normalize_path,
    operation_identity,
    path_shape,
)
from forge_doctor_api.analyzers.openapi.knowledge import SUPPORTED_FAMILIES, version_family
from forge_doctor_api.analyzers.openapi.loader import MAX_NODES, load_json, load_yaml
from forge_doctor_api.analyzers.openapi.refs import classify, lookup, split_pointer, unquote
from forge_doctor_api.core.context import ProjectContext

FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def _project(root: Path, paths: list[str] | None = None) -> OpenApiProjectModel:
    return load_openapi_project(ProjectContext.from_root(root), paths)


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def corpus() -> OpenApiProjectModel:
    return _project(FIXTURES)


def _docs(model: OpenApiProjectModel) -> dict[str, DocumentStatus]:
    return {d.location.path: d.status for d in model.documents}


# -- detection gate (§101) ---------------------------------------------------


@pytest.mark.parametrize(
    ("value", "status", "family"),
    [
        ({"openapi": "3.0.3"}, DocumentStatus.PARSED, "3.0"),
        ({"openapi": "3.1.0"}, DocumentStatus.PARSED, "3.1"),
        ({"openapi": "3.2.1"}, DocumentStatus.PARSED, "3.2"),
        ({"openapi": "3.1.9"}, DocumentStatus.PARSED, "3.1"),
        ({"openapi": "3.1.0-rc1"}, DocumentStatus.PARSED, "3.1"),
        ({"openapi": "4.0.0"}, DocumentStatus.UNSUPPORTED_VERSION, None),
        ({"openapi": "2.0.0"}, DocumentStatus.UNSUPPORTED_VERSION, None),
        ({"swagger": "2.0"}, DocumentStatus.UNSUPPORTED_VERSION, None),
        ({"openapi": 3.1}, DocumentStatus.INVALID_VERSION, None),
        ({"openapi": "3.1"}, DocumentStatus.INVALID_VERSION, None),
        ({"openapi": "latest"}, DocumentStatus.INVALID_VERSION, None),
        ({"openapi": None}, DocumentStatus.INVALID_VERSION, None),
        ({"openapi": "03.1.0"}, DocumentStatus.INVALID_VERSION, None),
        ({"paths": {"/x": {}}}, DocumentStatus.NOT_OPENAPI, None),
        ({"paths": {}, "info": {}, "components": {}}, DocumentStatus.NOT_OPENAPI, None),
        ({"OpenAPI": "3.1.0"}, DocumentStatus.NOT_OPENAPI, None),
        (["openapi", "3.1.0"], DocumentStatus.NOT_OPENAPI, None),
        ("openapi: 3.1.0", DocumentStatus.NOT_OPENAPI, None),
        (None, DocumentStatus.NOT_OPENAPI, None),
    ],
)
def test_detection_gate(value: Any, status: DocumentStatus, family: str | None) -> None:
    detection = detect_openapi(value)
    assert detection.status is status
    assert detection.family == family
    if status is not DocumentStatus.PARSED:
        assert detection.reason


def test_knowledge_pack_families() -> None:
    assert SUPPORTED_FAMILIES == ("3.0", "3.1", "3.2")
    assert version_family("3.2.1") == "3.2"
    assert version_family("3.3.0") is None


def test_discovery_ignores_weak_markers(corpus: OpenApiProjectModel) -> None:
    docs = _docs(corpus)
    # §100: random YAML named openapi.yml and JSON with `paths` but no marker.
    assert "adversarial/openapi.yml" not in docs
    assert "adversarial/paths-only.json" not in docs
    assert not any(op.location.path.startswith("adversarial/paths") for op in corpus.operations)


def test_explicit_paths_report_not_openapi() -> None:
    model = _project(FIXTURES, ["adversarial/openapi.yml", "adversarial/paths-only.json"])
    assert _docs(model) == {
        "adversarial/openapi.yml": DocumentStatus.NOT_OPENAPI,
        "adversarial/paths-only.json": DocumentStatus.NOT_OPENAPI,
    }
    assert {i.code for i in model.issues} == {IssueCode.NOT_OPENAPI}
    assert model.operations == () and model.paths == ()


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("openapi: 4.0.0\npaths: {}\n", DocumentStatus.UNSUPPORTED_VERSION),
        ("openapi: 3.1\npaths: {}\n", DocumentStatus.INVALID_VERSION),
        ("openapi: '3.1'\n", DocumentStatus.INVALID_VERSION),
        ("openapi: [3]\n", DocumentStatus.INVALID_VERSION),
        ("swagger: '2.0'\n", DocumentStatus.UNSUPPORTED_VERSION),
    ],
)
def test_bad_versions_are_structured_not_crashes(
    tmp_path: Path, text: str, status: DocumentStatus
) -> None:
    model = _project(_write(tmp_path, {"api.yaml": text}))
    assert _docs(model) == {"api.yaml": status}
    (issue,) = model.issues
    assert issue.code.value == status.value
    assert issue.location.path == "api.yaml" and issue.location.line == 1
    assert model.operations == ()


# -- positive: 3.0 YAML ------------------------------------------------------


def test_petstore_document(corpus: OpenApiProjectModel) -> None:
    (doc,) = [d for d in corpus.documents if d.location.path == "v30/petstore.yaml"]
    assert doc.status is DocumentStatus.PARSED
    assert (doc.openapi_version, doc.version_family, doc.format) == ("3.0.3", "3.0", "yaml")
    assert (doc.title, doc.api_version) == ("Petstore", "1.0.0")


def test_petstore_operations_and_identity(corpus: OpenApiProjectModel) -> None:
    ops = {op.identity: op for op in corpus.operations if op.location.path == "v30/petstore.yaml"}
    assert set(ops) == {
        "operation_id:listPets",
        "operation_id:getPet",
        "method_path:POST /pets",
        "method_path:POST callback:{$request.body#/callbackUrl}",
    }
    list_pets = ops["operation_id:listPets"]
    assert (list_pets.method, list_pets.path, list_pets.source) == ("GET", "/pets", "PATH")
    assert list_pets.location.line == 28 and list_pets.location.column == 5
    assert list_pets.pointer == "/paths/~1pets/get"
    assert list_pets.tags == ("pets",)
    assert list_pets.parameter_pointers == ("/paths/~1pets/parameters/0",)
    assert list_pets.response_pointers == (
        "/paths/~1pets/get/responses/200",
        "/paths/~1pets/get/responses/default",
    )
    post = ops["method_path:POST /pets"]
    assert post.request_body_pointer == "/paths/~1pets/post/requestBody"
    assert post.callback_pointers == ("/paths/~1pets/post/callbacks/onAdopted",)
    assert post.has_security and not list_pets.has_security
    callback_op = ops["method_path:POST callback:{$request.body#/callbackUrl}"]
    assert callback_op.source is OperationSource.CALLBACK


def test_petstore_collections(corpus: OpenApiProjectModel) -> None:
    def here(items: Any) -> list[Any]:
        return [i for i in items if i.location.path == "v30/petstore.yaml"]

    (server,) = here(corpus.servers)
    assert server.url == "https://{env}.example.com/v1"
    assert server.variables == {"env": {"default": "api", "enum": ["api", "staging"]}}
    assert [p.path for p in here(corpus.paths)] == ["/pets", "/pets/{petId}"]
    assert here(corpus.paths)[0].summary == "Pets collection"
    params = {p.pointer: p for p in here(corpus.parameters)}
    limit_ref = params["/paths/~1pets/parameters/0"]
    assert limit_ref.ref == "#/components/parameters/Limit"
    assert (limit_ref.name, limit_ref.location_in) == ("limit", "query")
    assert params["/components/parameters/Limit"].component_name == "Limit"
    pet_id = params["/paths/~1pets~1{petId}/get/parameters/0"]
    assert (pet_id.name, pet_id.location_in, pet_id.required) == ("petId", "path", True)
    (body,) = here(corpus.request_bodies)
    assert body.required and body.content_types == ("application/json",)
    statuses = {r.status for r in here(corpus.responses)}
    assert {"200", "201", "204", "default", None} <= statuses
    default = next(r for r in here(corpus.responses) if r.status == "default")
    assert default.ref == "#/components/responses/Error" and default.description == "error"
    assert {s.name for s in here(corpus.schemas)} == {"Pet", "Error"}
    (callback,) = here(corpus.callbacks)
    assert callback.expressions == ("{$request.body#/callbackUrl}",)
    schemes = {s.name: s for s in here(corpus.security_schemes)}
    assert (schemes["bearerAuth"].type, schemes["bearerAuth"].scheme) == ("http", "bearer")
    assert schemes["apiKey"].parameter_name == "X-Key"
    requirements = here(corpus.security_requirements)
    root_req = [r for r in requirements if r.owner_pointer == ""]
    assert [[s.name for s in r.schemes] for r in root_req] == [["bearerAuth"]]
    op_reqs = [r for r in requirements if r.owner_pointer == "/paths/~1pets/post"]
    assert [[s.name for s in r.schemes] for r in op_reqs] == [[], ["apiKey"]]
    assert [t.name for t in here(corpus.tags)] == ["pets"]
    assert {d.pointer for d in here(corpus.external_docs)} == {
        "/externalDocs",
        "/tags/0/externalDocs",
        "/components/schemas/Pet/externalDocs",
    }


def test_extensions_are_kept_not_dropped(corpus: OpenApiProjectModel) -> None:
    found = {(e.location.path, e.pointer): e for e in corpus.extensions}
    assert found[("v30/petstore.yaml", "/info/x-audience")].value == "public"
    assert found[("v30/petstore.yaml", "/paths/~1pets/post/x-rate-limit")].value == 10
    rate = found[("v30/petstore.yaml", "/paths/~1pets/post/x-rate-limit")]
    assert rate.owner_pointer == "/paths/~1pets/post" and rate.name == "x-rate-limit"
    assert rate.location.line == 44
    assert ("v30/petstore.yaml", "/paths/x-paths-note") in found
    assert ("crossfile/schemas/user.yaml", "/User/x-owner") in found
    # property named x-legacy and example payload keys are data, not extensions
    pointers = {p for _, p in found}
    assert not any("x-legacy" in p or "x-not-an-extension" in p for p in pointers)


def test_ref_keys_in_data_and_property_names_are_ignored(corpus: OpenApiProjectModel) -> None:
    refs = {r.ref for r in corpus.references}
    assert "not-a-ref" not in refs  # inside `example`
    assert "ignored" not in refs  # inside JSON Schema `examples` array
    petstore_paths = [p for p in corpus.paths if p.location.path == "v30/petstore.yaml"]
    assert all(not p.path.startswith("x-") for p in petstore_paths)


# -- positive: 3.1 JSON / 3.2 YAML ------------------------------------------


def test_openapi_31_json(corpus: OpenApiProjectModel) -> None:
    (doc,) = [d for d in corpus.documents if d.location.path == "v31/api.json"]
    assert (doc.format, doc.version_family) == ("json", "3.1")
    assert doc.json_schema_dialect == "https://spec.openapis.org/oas/3.1/dialect/base"
    (webhook,) = corpus.webhooks
    assert (webhook.name, webhook.methods) == ("newPet", ("post",))
    (op,) = [o for o in corpus.operations if o.source is OperationSource.WEBHOOK]
    assert op.identity == "method_path:POST webhook:newPet"
    assert op.location.line == 7
    pet = next(s for s in corpus.schemas if s.location.path == "v31/api.json" and s.name == "Pet")
    assert pet.content["type"] == ["object", "null"]


def test_openapi_32_constructs(corpus: OpenApiProjectModel) -> None:
    ops = {o.identity: o for o in corpus.operations if o.location.path == "v32/api.yaml"}
    assert set(ops) == {"operation_id:searchQuery", "method_path:PURGE /search"}
    assert ops["operation_id:searchQuery"].method == "QUERY"
    (doc,) = [d for d in corpus.documents if d.location.path == "v32/api.yaml"]
    assert doc.self_uri == "https://example.com/api/openapi.yaml"
    tags = {t.name: t.parent for t in corpus.tags if t.location.path == "v32/api.yaml"}
    assert tags == {"search": None, "advanced": "search"}


def test_mixed_version_constructs_do_not_crash(tmp_path: Path) -> None:
    # 3.0 document using 3.1-only constructs (webhooks, type arrays): modelled as-is.
    text = (
        "openapi: 3.0.3\ninfo: {title: t, version: '1'}\n"
        "webhooks:\n  ping:\n    post:\n      responses: {'200': {description: ok}}\n"
        "components:\n  schemas:\n    S: {type: [string, 'null'], nullable: true}\n"
    )
    model = _project(_write(tmp_path, {"api.yaml": text}))
    assert model.documents[0].version_family == "3.0"
    assert [w.name for w in model.webhooks] == ["ping"]
    assert model.schemas[0].content["type"] == ["string", "null"]
    assert model.issues == ()


# -- $ref resolution: local / relative / cross-file -------------------------


def test_cross_file_refs(corpus: OpenApiProjectModel) -> None:
    docs = _docs(corpus)
    assert docs["crossfile/paths/users.yaml"] is DocumentStatus.FRAGMENT
    assert docs["crossfile/schemas/user.yaml"] is DocumentStatus.FRAGMENT
    assert docs["crossfile/schemas/group.yaml"] is DocumentStatus.FRAGMENT
    (op,) = [o for o in corpus.operations if o.identity == "operation_id:listUsers"]
    assert op.path == "/users"
    assert (op.location.path, op.pointer, op.location.line) == (
        "crossfile/paths/users.yaml",
        "/get",
        1,
    )
    refs = {(r.location.path, r.ref): r for r in corpus.references}
    users = refs[("crossfile/root.yaml", "paths/users.yaml")]
    assert users.status is RefStatus.RESOLVED
    assert (users.target_path, users.target_pointer) == ("crossfile/paths/users.yaml", "")
    nested = refs[("crossfile/paths/users.yaml", "../schemas/user.yaml#/User")]
    assert (nested.target_path, nested.target_pointer) == ("crossfile/schemas/user.yaml", "/User")
    local = refs[("crossfile/schemas/user.yaml", "#/User")]
    assert (local.target_path, local.status) == ("crossfile/schemas/user.yaml", RefStatus.RESOLVED)


def test_missing_ref_target_is_recorded(corpus: OpenApiProjectModel) -> None:
    refs = {r.ref: r for r in corpus.references}
    missing = refs["schemas/user.yaml#/DoesNotExist"]
    assert missing.status is RefStatus.MISSING and missing.target_path is None
    issue = next(i for i in corpus.issues if i.code is IssueCode.MISSING_REF_TARGET)
    assert (issue.location.path, issue.location.line) == ("crossfile/root.yaml", 17)


def test_missing_file_and_malformed_fragment(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "api.yaml": (
                "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths: {}\n"
                "components:\n  schemas:\n"
                "    A: {$ref: gone.yaml#/A}\n    B: {$ref: broken.yaml#/B}\n"
                "    C: {$ref: frag.json#/C}\n"
            ),
            "broken.yaml": "B: [unclosed\n",
            "frag.json": '{"C": {"type": "string"}}',
        },
    )
    model = _project(root)
    statuses = {r.ref: r.status for r in model.references}
    assert statuses == {
        "gone.yaml#/A": RefStatus.MISSING,
        "broken.yaml#/B": RefStatus.MISSING,
        "frag.json#/C": RefStatus.RESOLVED,
    }
    assert _docs(model) == {
        "api.yaml": DocumentStatus.PARSED,
        "broken.yaml": DocumentStatus.MALFORMED,
        "frag.json": DocumentStatus.FRAGMENT,
        "gone.yaml": DocumentStatus.UNREADABLE,
    }


def test_remote_refs_recorded_never_fetched(
    corpus: OpenApiProjectModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_: Any, **__: Any) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    model = _project(FIXTURES)  # would raise if anything tried to connect
    unresolved = {u.ref: u.reason for u in model.unresolved_external_refs}
    assert unresolved == {
        "http://example.com/schemas.yaml#/Pet": RefStatus.EXTERNAL,
        "https://example.com/schemas.yaml#/Pet": RefStatus.EXTERNAL,
        "urn:example:pet": RefStatus.EXTERNAL,
        "file:///etc/passwd": RefStatus.EXTERNAL,
        "/etc/openapi.yaml": RefStatus.OUTSIDE_ROOT,
        "../../outside.yaml": RefStatus.OUTSIDE_ROOT,
        "https://example.com/remote.yaml#/paths/~1remote": RefStatus.EXTERNAL,
    }
    assert model == corpus
    remote_path = next(p for p in model.paths if p.path == "/remote")
    assert remote_path.ref is not None
    assert not any(o.path == "/remote" for o in model.operations)


@pytest.mark.parametrize(
    ("ref", "status", "path", "pointer"),
    [
        ("#/components/schemas/A", RefStatus.RESOLVED, "api/root.yaml", "/components/schemas/A"),
        ("#", RefStatus.RESOLVED, "api/root.yaml", ""),
        ("common.yaml", RefStatus.RESOLVED, "api/common.yaml", ""),
        ("./x/../common.yaml#/A", RefStatus.RESOLVED, "api/common.yaml", "/A"),
        ("../shared/s.json#/S", RefStatus.RESOLVED, "shared/s.json", "/S"),
        ("#/paths/~1users~1%7Bid%7D", RefStatus.RESOLVED, "api/root.yaml", "/paths/~1users~1{id}"),
        ("../../escape.yaml", RefStatus.OUTSIDE_ROOT, None, None),
        ("/abs.yaml", RefStatus.OUTSIDE_ROOT, None, None),
        ("..\\win.yaml", RefStatus.OUTSIDE_ROOT, None, None),
        ("https://x.test/a.yaml", RefStatus.EXTERNAL, None, None),
        ("//x.test/a.yaml", RefStatus.EXTERNAL, None, None),
        ("C:/a.yaml", RefStatus.EXTERNAL, None, None),
        ("#anchor", RefStatus.INVALID, None, None),
        ("#/bad~2escape", RefStatus.INVALID, None, None),
        ("", RefStatus.INVALID, None, None),
        (42, RefStatus.INVALID, None, None),
    ],
)
def test_classify_refs(ref: Any, status: RefStatus, path: str | None, pointer: str | None) -> None:
    target = classify(ref, "api/root.yaml")
    assert (target.status, target.path, target.pointer) == (status, path, pointer)


def test_pointer_helpers() -> None:
    assert split_pointer("/a~1b/~0c") == ["a/b", "~c"]
    assert split_pointer("a") is None
    assert unquote("%7Bid%7D/caf%C3%A9/%zz") == "{id}/café/%zz"
    data = {"a": [{"b": 1}]}
    assert lookup(data, "/a/0/b") == 1
    assert lookup(data, "") is data
    for missing in ("/a/1", "/a/01", "/a/x", "/z", "/a/0/b/c"):
        assert lookup(data, missing) is not None and lookup(data, missing) != 1


# -- cycles (§10.3) -----------------------------------------------------------


def test_cycles_detected_and_classified(corpus: OpenApiProjectModel) -> None:
    cycles = {c.members: c for c in corpus.cycles}
    rec = "adversarial/recursive.yaml#/components"
    assert cycles[(f"{rec}/schemas/Self",)].kind is CycleKind.ALIAS
    assert cycles[(f"{rec}/parameters/P1",)].kind is CycleKind.ALIAS
    assert cycles[(f"{rec}/pathItems/LoopA", f"{rec}/pathItems/LoopB")].kind is CycleKind.ALIAS
    assert cycles[(f"{rec}/responses/R1", f"{rec}/responses/R2")].kind is CycleKind.ALIAS
    assert cycles[(f"{rec}/schemas/Tree",)].kind is CycleKind.RECURSIVE
    assert cycles[(f"{rec}/schemas/A", f"{rec}/schemas/B")].kind is CycleKind.RECURSIVE
    cross = cycles[("crossfile/schemas/group.yaml#/Group", "crossfile/schemas/user.yaml#/User")]
    assert cross.kind is CycleKind.RECURSIVE
    assert (cross.location.path, cross.location.line) == ("crossfile/schemas/group.yaml", 7)
    pet = cycles[("v30/petstore.yaml#/components/schemas/Pet",)]
    assert (pet.kind, pet.location.line, pet.pointer) == (
        CycleKind.RECURSIVE,
        94,
        "/components/schemas/Pet/properties/parent",
    )
    assert (f"{rec}/schemas/Tree",) in cycles
    assert not any("Error" in m for c in corpus.cycles for m in c.members)


def test_alias_loops_terminate_without_operations(corpus: OpenApiProjectModel) -> None:
    loop = next(p for p in corpus.paths if p.path == "/loop")
    assert loop.ref == "#/components/pathItems/LoopA"
    assert not any(o.path == "/loop" for o in corpus.operations)
    (self_op,) = [o for o in corpus.operations if o.path == "/self"]
    param = next(p for p in corpus.parameters if p.pointer == "/paths/~1self/get/parameters/0")
    assert param.name is None and param.ref == "#/components/parameters/P1"
    assert self_op.identity == "method_path:GET /self"


def test_deep_and_long_ref_cycles(tmp_path: Path) -> None:
    n = 2000
    schemas = "".join(
        f"    S{i}:\n      properties:\n"
        f"        next: {{$ref: '#/components/schemas/S{(i + 1) % n}'}}\n"
        for i in range(n)
    )
    chain = (
        "".join(f"    C{i}: {{$ref: '#/components/schemas/C{i + 1}'}}\n" for i in range(n))
        + f"    C{n}: {{type: string}}\n"
    )
    text = (
        "openapi: 3.1.0\ninfo: {title: t, version: '1'}\n"
        "paths:\n  /deep:\n    get:\n      responses:\n"
        "        '200': {description: ok, content: {application/json: "
        "{schema: {$ref: '#/components/schemas/C0'}}}}\n"
        f"components:\n  schemas:\n{schemas}{chain}"
    )
    model = _project(_write(tmp_path, {"api.yaml": text}))
    (cycle,) = model.cycles
    assert cycle.kind is CycleKind.RECURSIVE and len(cycle.members) == n
    assert all(r.status is RefStatus.RESOLVED for r in model.references)
    assert [o.path for o in model.operations] == ["/deep"]


def test_cross_file_alias_cycle(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "api.yaml": (
                "openapi: 3.1.0\ninfo: {title: t, version: '1'}\n"
                "paths:\n  /p: {$ref: 'a.yaml#/P'}\n"
            ),
            "a.yaml": "P: {$ref: 'b.yaml#/P'}\n",
            "b.yaml": "P: {$ref: 'a.yaml#/P'}\n",
        },
    )
    model = _project(root)
    (cycle,) = model.cycles
    assert cycle.kind is CycleKind.ALIAS
    assert cycle.members == ("a.yaml#/P", "b.yaml#/P")
    assert model.operations == ()


# -- malformed / hostile input ----------------------------------------------


def test_malformed_spec_with_marker_is_reported(corpus: OpenApiProjectModel) -> None:
    assert _docs(corpus)["adversarial/malformed.yaml"] is DocumentStatus.MALFORMED
    issue = next(i for i in corpus.issues if i.location.path == "adversarial/malformed.yaml")
    assert issue.code is IssueCode.MALFORMED and issue.location.line == 5


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("custom-tag.yaml", "openapi: 3.1.0\ninfo: !Ref foo\n"),
        ("python-tag.yaml", "openapi: 3.1.0\nx: !!python/object/apply:os.system ['echo hi']\n"),
        ("multi.yaml", "openapi: 3.1.0\n---\nopenapi: 3.0.0\n"),
        ("complex-key.yaml", "openapi: 3.1.0\n? [a, b]\n: c\n"),
        ("recursive-alias.yaml", "openapi: 3.1.0\nx: &a [*a]\n"),
        ("bad.json", '{"openapi": "3.1.0", "paths": {'),
        ("nan.json", '{"openapi": "3.1.0", "x": NaN}'),
        ("tabs.yaml", "openapi: 3.1.0\ninfo:\n\ttitle: x\n"),
    ],
)
def test_malformed_inputs_never_crash(tmp_path: Path, name: str, text: str) -> None:
    model = _project(_write(tmp_path, {name: text}))
    assert _docs(model) == {name: DocumentStatus.MALFORMED}
    assert [i.code for i in model.issues] == [IssueCode.MALFORMED]


def test_billion_laughs_is_bounded(tmp_path: Path) -> None:
    lines = ["openapi: 3.1.0", "a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for i in range(1, 9):
        lines.append(f"a{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * 10) + "]")
    model = _project(_write(tmp_path, {"lol.yaml": "\n".join(lines) + "\n"}))
    assert _docs(model) == {"lol.yaml": DocumentStatus.MALFORMED}
    assert str(MAX_NODES) in model.issues[0].message


@pytest.mark.parametrize("fmt", ["json", "yaml"])
def test_deep_nesting_does_not_crash(tmp_path: Path, fmt: str) -> None:
    depth = 5000
    if fmt == "json":
        text = '{"openapi": "3.1.0", "x": ' + "[" * depth + "]" * depth + "}"
    else:
        text = "openapi: 3.1.0\nx: " + "[" * depth + "]" * depth + "\n"
    model = _project(_write(tmp_path, {f"deep.{fmt}": text}))
    (doc,) = model.documents
    assert doc.status in (DocumentStatus.MALFORMED, DocumentStatus.PARSED)


def test_unreadable_and_non_utf8(tmp_path: Path) -> None:
    (tmp_path / "latin.yaml").write_bytes("openapi: 3.1.0\ntitle: caf\xe9\n".encode("latin-1"))
    model = _project(tmp_path, ["latin.yaml", "missing.yaml", "../outside.yaml"])
    assert _docs(model) == {
        "latin.yaml": DocumentStatus.UNREADABLE,
        "missing.yaml": DocumentStatus.UNREADABLE,
        "../outside.yaml": DocumentStatus.UNREADABLE,
    }
    assert {i.code for i in model.issues} == {IssueCode.UNREADABLE}


def test_duplicate_keys_reported_last_wins(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        {
            "a.yaml": (
                "openapi: 3.1.0\ninfo: {title: one, version: '1'}\n"
                "info: {title: two, version: '1'}\n"
            ),
            "b.json": '{"openapi": "3.1.0", "info": {"title": "one"}, "info": {"title": "two"}}',
        },
    )
    model = _project(root)
    assert {d.title for d in model.documents} == {"two"}
    dupes = [i for i in model.issues if i.code is IssueCode.DUPLICATE_KEY]
    assert sorted(i.location.path for i in dupes) == ["a.yaml", "b.json"]
    assert next(i for i in dupes if i.location.path == "a.yaml").location.line == 3


def test_yaml_scalars_stay_json_compatible() -> None:
    loaded = load_yaml(
        "openapi: 3.1.0\ndate: 2024-01-01\ninf: .inf\nyes: yes\n200: ok\n"
        "base: &b {x: 1}\nmerged:\n  <<: *b\n  y: 2\n"
    )
    assert loaded.ok
    assert loaded.value["date"] == "2024-01-01"
    assert loaded.value["inf"] == ".inf"
    assert loaded.value["200"] == "ok"
    assert loaded.value["merged"] == {"x": 1, "y": 2}
    assert loaded.locations["/merged/y"] == (9, 3)
    assert load_json('{"big": 1e999}').value == {"big": "1e999"}


def test_json_locations_fall_back_gracefully() -> None:
    loaded = load_json('{"openapi": "3.1.0",\n "info": {"title": "t"}}')
    assert loaded.locations["/info/title"] == (2, 11)


def test_invalid_ref_values(tmp_path: Path) -> None:
    text = (
        "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths: {}\n"
        "components:\n  schemas:\n    A: {$ref: 42}\n    B: {$ref: '#anchor'}\n"
    )
    model = _project(_write(tmp_path, {"api.yaml": text}))
    assert {r.status for r in model.references} == {RefStatus.INVALID}
    assert [i.code for i in model.issues] == [IssueCode.INVALID_REF, IssueCode.INVALID_REF]


# -- dynamic / unknown --------------------------------------------------------


def test_dynamic_ref_is_unknown_not_resolved(corpus: OpenApiProjectModel) -> None:
    (dynamic,) = [r for r in corpus.references if r.keyword == "$dynamicRef"]
    assert dynamic.status is RefStatus.DYNAMIC
    assert dynamic.target_path is None and dynamic.target_pointer is None
    assert dynamic.location.path == "v31/api.json"


# -- operation identity (§181, §182) ----------------------------------------


def test_operation_identity_prefers_operation_id() -> None:
    assert operation_identity("get", "/users/{id}", "getUser") == "operation_id:getUser"
    assert operation_identity("get", "/users/{id}", "  ") == "method_path:GET /users/{id}"
    assert operation_identity(" post ", " /users ", None) == "method_path:POST /users"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("/users/{id}", "/users/{userId}"),
        ("/users", "/users/"),
        ("/Users", "/users"),
        ("/a%20b", "/a b"),
        ("/users/{id}", "/users/{id}.json"),
    ],
)
def test_path_normalization_is_conservative(a: str, b: str) -> None:
    assert operation_identity("GET", a) != operation_identity("GET", b)
    assert normalize_path(a) != normalize_path(b)


def test_path_shape_flags_but_never_merges() -> None:
    assert path_shape("/users/{id}") == path_shape("/users/{userId}") == "/users/{}"
    assert operation_identity("GET", "/users/{id}") != operation_identity("GET", "/users/{userId}")


def test_structurally_similar_paths_stay_distinct(tmp_path: Path) -> None:
    text = (
        "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths:\n"
        "  /users/{id}:\n    get: {responses: {'200': {description: ok}}}\n"
        "  /users/{userId}:\n    get: {responses: {'200': {description: ok}}}\n"
    )
    model = _project(_write(tmp_path, {"api.yaml": text}))
    assert sorted(o.identity for o in model.operations) == [
        "method_path:GET /users/{id}",
        "method_path:GET /users/{userId}",
    ]


# -- serialization & determinism ---------------------------------------------


def test_serialization_round_trip(corpus: OpenApiProjectModel) -> None:
    text = corpus.to_json()
    assert json.loads(text)["schema_version"] == OPENAPI_MODEL_SCHEMA_VERSION
    restored = OpenApiProjectModel.from_json(text)
    assert restored.to_json() == text
    assert restored == corpus


def test_repeated_runs_are_byte_identical(corpus: OpenApiProjectModel) -> None:
    assert _project(FIXTURES).to_json() == corpus.to_json()


def test_explicit_path_order_does_not_matter() -> None:
    paths = [
        "v30/petstore.yaml",
        "v31/api.json",
        "v32/api.yaml",
        "crossfile/root.yaml",
        "adversarial/recursive.yaml",
    ]
    baseline = _project(FIXTURES, paths).to_json()
    for seed in range(5):
        shuffled = paths[:]
        random.Random(seed).shuffle(shuffled)
        assert _project(FIXTURES, shuffled).to_json() == baseline


def test_copy_order_does_not_matter(tmp_path: Path) -> None:
    files = sorted(p for p in FIXTURES.rglob("*") if p.is_file())
    outputs = []
    for seed in range(3):
        target = tmp_path / f"copy{seed}"
        order = files[:]
        random.Random(seed).shuffle(order)
        for source in order:
            dest = target / source.relative_to(FIXTURES)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        outputs.append(_project(target).to_json())
    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0] == _project(FIXTURES).to_json()


def test_collections_are_sorted(corpus: OpenApiProjectModel) -> None:
    for name in ("operations", "parameters", "references", "extensions", "cycles"):
        items = getattr(corpus, name)
        keys = [(i.location.path, getattr(i, "pointer", "")) for i in items]
        assert keys == sorted(keys), name


def test_discovery_skips_hidden_and_vendor_dirs(tmp_path: Path) -> None:
    spec = "openapi: 3.1.0\ninfo: {title: t, version: '1'}\npaths: {}\n"
    root = _write(
        tmp_path,
        {"api.yaml": spec, ".venv/x/api.yaml": spec, "node_modules/p/openapi.json": "{}"},
    )
    assert list(_docs(_project(root))) == ["api.yaml"]


def test_empty_project(tmp_path: Path) -> None:
    model = _project(tmp_path)
    assert model == OpenApiProjectModel(schema_version=OPENAPI_MODEL_SCHEMA_VERSION)
