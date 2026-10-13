"""ApiVersionModel + lifecycle tests (spec 010, §7.4, §18, §19)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.version import (
    LifecycleState,
    VersionMechanism,
    detect_version_model,
)
from forge_doctor_api.core.context import ProjectContext


def _model(root: Path, spec: str):
    root.mkdir(parents=True, exist_ok=True)
    (root / "api.yaml").write_text(spec, encoding="utf-8")
    return load_openapi_project(ProjectContext.from_root(root), ["api.yaml"])


def _versions(model) -> set[tuple[str, str]]:
    return {(v.mechanism.value, v.identifier) for v in model.versions}


BASE = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /v2/users/{id}:
    get:
      operationId: getUser
      parameters:
        - {name: api-version, in: header, schema: {const: "2"}}
      responses:
        '200':
          description: ok
          content:
            application/vnd.t.user.v2+json:
              schema: {type: object}
"""


def test_uri_version_detected(tmp_path: Path) -> None:
    model = detect_version_model(_model(tmp_path, BASE))
    assert (VersionMechanism.URI.value, "v2") in _versions(model)


def test_header_version_detected(tmp_path: Path) -> None:
    model = detect_version_model(_model(tmp_path, BASE))
    assert (VersionMechanism.HEADER.value, "2") in _versions(model)


def test_media_type_version_detected(tmp_path: Path) -> None:
    model = detect_version_model(_model(tmp_path, BASE))
    assert (VersionMechanism.MEDIA_TYPE.value, "2") in _versions(model)


def test_media_type_version_param(tmp_path: Path) -> None:
    spec = BASE.replace("application/vnd.t.user.v2+json", 'application/json; version="3"')
    model = detect_version_model(_model(tmp_path, spec))
    assert (VersionMechanism.MEDIA_TYPE.value, "3") in _versions(model)


def test_server_url_version(tmp_path: Path) -> None:
    spec = BASE.replace(
        "paths:", "servers: [{url: 'https://api.example.com/v1'}]\npaths:"
    )
    model = detect_version_model(_model(tmp_path, spec))
    assert (VersionMechanism.URI.value, "v1") in _versions(model)


def test_version_free_api_is_unknown(tmp_path: Path) -> None:
    spec = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /users:
    get:
      operationId: list
      responses:
        '200': {description: ok}
"""
    model = detect_version_model(_model(tmp_path, spec))
    assert model.versions == ()
    assert model.lifecycle is LifecycleState.UNKNOWN
    assert any(u.subject == "versioning" for u in model.unknowns)


def test_no_active_masquerade(tmp_path: Path) -> None:
    """A live-looking API without lifecycle markers is UNKNOWN, not ACTIVE."""
    model = detect_version_model(_model(tmp_path, BASE))
    assert model.lifecycle is LifecycleState.UNKNOWN


def test_deprecated_flag(tmp_path: Path) -> None:
    spec = BASE.replace(
        "      operationId: getUser",
        "      operationId: getUser\n      deprecated: true",
    )
    model = detect_version_model(_model(tmp_path, spec))
    assert model.deprecation.deprecated
    assert model.lifecycle is LifecycleState.DEPRECATED
    assert model.deprecation.evidence


def test_sunset_date(tmp_path: Path) -> None:
    spec = BASE.replace(
        "info: {title: T, version: \"1.0\"}",
        "info:\n  title: T\n  version: \"1.0\"\n"
        "  x-sunset-date: \"2030-01-01\"\n  deprecated: true",
    )
    model = detect_version_model(_model(tmp_path, spec))
    assert model.deprecation.sunset_date == "2030-01-01"
    assert model.lifecycle is LifecycleState.SUNSET


def test_explicit_lifecycle_overrides(tmp_path: Path) -> None:
    spec = BASE.replace(
        "info: {title: T, version: \"1.0\"}",
        "info:\n  title: T\n  version: \"1.0\"\n  x-lifecycle: retired",
    )
    model = detect_version_model(_model(tmp_path, spec))
    assert model.lifecycle is LifecycleState.RETIRED
    assert model.lifecycle_evidence


def test_replacement_recorded(tmp_path: Path) -> None:
    spec = BASE.replace(
        "info: {title: T, version: \"1.0\"}",
        "info:\n  title: T\n  version: \"1.0\"\n  x-replaced-by: \"/v3/users\"",
    )
    model = detect_version_model(_model(tmp_path, spec))
    assert model.deprecation.replacement == "/v3/users"


def test_runtime_fields_are_unknowns(tmp_path: Path) -> None:
    model = detect_version_model(_model(tmp_path, BASE))
    assert any("traffic_remaining" in u.missing for u in model.unknowns)


def test_determinism(tmp_path: Path) -> None:
    a = detect_version_model(_model(tmp_path / "a", BASE))
    b = detect_version_model(_model(tmp_path / "b", BASE))
    assert [v.to_dict() for v in a.versions] == [v.to_dict() for v in b.versions]
    assert a.lifecycle is b.lifecycle


def test_malformed_input(tmp_path: Path) -> None:
    model = detect_version_model(_model(tmp_path, "not: [valid"))
    assert model.versions == ()
    assert model.lifecycle is LifecycleState.UNKNOWN
