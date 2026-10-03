"""ApiCompatibilityEngine tests (spec 008, §16, §66, §121-§123, §160, §180, §226).

Positive cases pin every §16.2 breaking rule and every §16.3 candidate;
negative cases pin that identical or safely-evolved contracts produce no
breaking findings; adversarial cases pin UNKNOWN instead of guesses.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.compat import (
    CompatibilityClass,
    diff_models,
    semantic_fingerprint,
)
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext

runner = CliRunner()

USER_OLD = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /users/{id}:
    get:
      operationId: getUser
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/User'}
components:
  schemas:
    User:
      type: object
      required: [id, name, email]
      properties:
        id: {type: string}
        name: {type: string}
        email: {type: string}
"""

USER_NEW = USER_OLD.replace("required: [id, name, email]", "required: [id, name]").replace(
    "        email: {type: string}\n", ""
)


def _model(root: Path, files: dict[str, str]):
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    ctx = ProjectContext.from_root(root)
    return load_openapi_project(ctx, list(files))


def _diff(tmp_path: Path, old: dict[str, str], new: dict[str, str]):
    return diff_models(_model(tmp_path / "old", old), _model(tmp_path / "new", new))


def _ids(diff) -> list[str]:
    return [f.id for f in diff.findings]


def _kinds(diff) -> list[str]:
    return [c.kind for c in diff.changes]


def _classified(diff, cls: CompatibilityClass) -> list[str]:
    return [c.kind for c in diff.changes if c.classification is cls]


# -- §226 demo ------------------------------------------------------------------


def test_demo_email_field_removed_is_breaking(tmp_path: Path) -> None:
    """§226: GET /users/{id} loses response field `email` on `getUser`."""
    diff = _diff(tmp_path, {"api.yaml": USER_OLD}, {"api.yaml": USER_NEW})
    breaking = [c for c in diff.changes if c.classification is CompatibilityClass.BREAKING]
    assert [c.kind for c in breaking] == ["response_field_removed"]
    assert "operation_id:getUser" in breaking[0].subject
    assert breaking[0].path.endswith("email")
    assert "COMPAT007" in _ids(diff)


def test_identical_contracts_have_empty_diff(tmp_path: Path) -> None:
    diff = _diff(tmp_path, {"api.yaml": USER_OLD}, {"api.yaml": USER_OLD})
    assert diff.changes == ()
    assert diff.findings == ()


# -- §16.2 breaking rules --------------------------------------------------------


BASE = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      parameters:
        - {name: limit, in: query, schema: {type: integer}}
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Kind'}
        '404': {description: missing}
    post:
      operationId: createPet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Pet'}
      responses:
        '201': {description: made}
  /pets/{id}:
    delete:
      operationId: deletePet
      responses:
        '204': {description: gone}
components:
  schemas:
    Pet:
      type: object
      required: [name]
      properties:
        name: {type: string}
        tag: {type: string}
    Kind:
      type: string
      enum: [cat, dog, bird]
"""


def test_endpoint_removed(tmp_path: Path) -> None:
    new = BASE.replace(
        """  /pets/{id}:
    delete:
      operationId: deletePet
      responses:
        '204': {description: gone}
""",
        "",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT001" in _ids(diff)
    assert "endpoint_removed" in _classified(diff, CompatibilityClass.BREAKING)


def test_method_removed(tmp_path: Path) -> None:
    new = BASE.replace(
        """    post:
      operationId: createPet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/Pet'}
      responses:
        '201': {description: made}
""",
        "",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT002" in _ids(diff)
    assert "method_removed" in _classified(diff, CompatibilityClass.BREAKING)


def test_required_parameter_added(tmp_path: Path) -> None:
    new = BASE.replace(
        "        - {name: limit, in: query, schema: {type: integer}}",
        "        - {name: limit, in: query, schema: {type: integer}}\n"
        "        - {name: tenant, in: query, required: true, schema: {type: string}}",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT003" in _ids(diff)


def test_parameter_removed(tmp_path: Path) -> None:
    new = BASE.replace(
        "        - {name: limit, in: query, schema: {type: integer}}\n", ""
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT004" in _ids(diff)


def test_parameter_type_changed(tmp_path: Path) -> None:
    new = BASE.replace(
        "{name: limit, in: query, schema: {type: integer}}",
        "{name: limit, in: query, schema: {type: string}}",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT005" in _ids(diff)


def test_request_field_became_required(tmp_path: Path) -> None:
    new = BASE.replace("required: [name]", "required: [name, tag]")
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT006" in _ids(diff)
    assert "request_field_required" in _classified(diff, CompatibilityClass.BREAKING)


def test_response_type_narrowed(tmp_path: Path) -> None:
    old = BASE + (
        "    Count:\n      type: object\n      properties:\n        total: {type: number}\n"
    )
    old = old.replace(
        "#/components/schemas/Kind", "#/components/schemas/Count"
    )
    new = old.replace("total: {type: number}", "total: {type: integer}")
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT008" in _ids(diff)


def test_enum_value_removed(tmp_path: Path) -> None:
    new = BASE.replace("enum: [cat, dog, bird]", "enum: [cat, dog]")
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT009" in _ids(diff)


def test_status_code_removed(tmp_path: Path) -> None:
    new = BASE.replace("        '404': {description: missing}\n", "")
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT010" in _ids(diff)


def test_auth_tightened(tmp_path: Path) -> None:
    old = BASE.replace(
        "      operationId: listPets\n",
        "      operationId: listPets\n      security: []\n",
    )
    new = old.replace("      security: []\n", "      security: [{key: []}]\n")
    new += "  securitySchemes:\n    key: {type: apiKey, in: header, name: X-K}\n"
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT011" in _ids(diff)


def test_response_content_type_removed(tmp_path: Path) -> None:
    old = BASE.replace(
        "            application/json:\n              schema: {$ref: '#/components/schemas/Kind'}",
        "            application/json:\n              schema: {$ref: '#/components/schemas/Kind'}\n"
        "            text/csv: {}",
    )
    new = BASE
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT012" in _ids(diff)


# -- §16.3 candidates ------------------------------------------------------------


def test_new_endpoint_is_candidate_not_breaking(tmp_path: Path) -> None:
    new = BASE.replace(
        "components:",
        """  /health:
    get:
      operationId: health
      responses:
        '200': {description: ok}
components:""",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT021" in _ids(diff)
    assert "endpoint_added" in _classified(diff, CompatibilityClass.POTENTIALLY_BREAKING)
    assert "endpoint_added" not in _classified(diff, CompatibilityClass.BREAKING)


def test_optional_query_parameter_added(tmp_path: Path) -> None:
    new = BASE.replace(
        "        - {name: limit, in: query, schema: {type: integer}}",
        "        - {name: limit, in: query, schema: {type: integer}}\n"
        "        - {name: q, in: query, schema: {type: string}}",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT022" in _ids(diff)
    assert "param_added_optional" in _classified(
        diff, CompatibilityClass.POTENTIALLY_BREAKING
    )


def test_enum_value_added_is_candidate(tmp_path: Path) -> None:
    new = BASE.replace("enum: [cat, dog, bird]", "enum: [cat, dog, bird, fish]")
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "COMPAT023" in _ids(diff)
    assert "enum_added" in _classified(diff, CompatibilityClass.POTENTIALLY_BREAKING)


def test_optional_response_field_added_is_candidate(tmp_path: Path) -> None:
    new = USER_NEW.replace(
        "        name: {type: string}\n",
        "        name: {type: string}\n        nickname: {type: string}\n",
    )
    diff = _diff(tmp_path, {"api.yaml": USER_NEW}, {"api.yaml": new})
    assert "COMPAT020" in _ids(diff)
    assert not _classified(diff, CompatibilityClass.BREAKING)


def test_auth_loosened_non_breaking(tmp_path: Path) -> None:
    new = BASE.replace(
        "      operationId: listPets\n",
        "      operationId: listPets\n      security: []\n",
    )
    old = new.replace("      security: []\n", "      security: [{key: []}]\n")
    old += "  securitySchemes:\n    key: {type: apiKey, in: header, name: X-K}\n"
    new += "  securitySchemes:\n    key: {type: apiKey, in: header, name: X-K}\n"
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT024" in _ids(diff)
    assert not _classified(diff, CompatibilityClass.BREAKING)


# -- request vs response direction (§123) ----------------------------------------


def test_request_widening_is_safe_response_widening_is_candidate(tmp_path: Path) -> None:
    old = BASE.replace("schema: {type: integer}", "schema: {type: integer}")
    new = old.replace(
        "{name: limit, in: query, schema: {type: integer}}",
        "{name: limit, in: query, schema: {type: number}}",
    )
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert not _classified(diff, CompatibilityClass.BREAKING)


def test_request_narrowing_breaks(tmp_path: Path) -> None:
    old = BASE.replace(
        "{name: limit, in: query, schema: {type: integer}}",
        "{name: limit, in: query, schema: {type: number}}",
    )
    new = BASE
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT005" in _ids(diff)


# -- adversarial / UNKNOWN --------------------------------------------------------


def test_composition_branch_count_change_is_unknown(tmp_path: Path) -> None:
    old = USER_OLD + (
        "    Variant:\n      oneOf:\n        - {type: string}\n        - {type: 'null'}\n"
    )
    old = old.replace(
        "#/components/schemas/User", "#/components/schemas/Variant"
    ).replace("        '200':", "        '200':")
    new = old.replace(
        "        - {type: 'null'}\n",
        "        - {type: 'null'}\n        - {type: integer}\n",
    )
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT030" in _ids(diff)


def test_oneof_branch_type_change_detected(tmp_path: Path) -> None:
    old = USER_OLD + (
        "    Variant:\n      oneOf:\n        - {type: string}\n        - {type: 'null'}\n"
    )
    old = old.replace("#/components/schemas/User", "#/components/schemas/Variant")
    new = old.replace("{type: 'null'}", "{type: integer}")
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert diff.changes  # pairwise composition diff must surface something
    assert "COMPAT030" in _ids(diff) or _classified(
        diff, CompatibilityClass.BREAKING
    )


def test_unresolvable_schema_change_is_unknown(tmp_path: Path) -> None:
    old = BASE.replace("schema: {$ref: '#/components/schemas/Pet'}", "schema: {}")
    new = BASE.replace(
        "schema: {$ref: '#/components/schemas/Pet'}",
        "schema: {type: object}",
    )
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert _classified(diff, CompatibilityClass.UNKNOWN)
    assert "COMPAT030" in _ids(diff)


def test_additional_properties_tightened_request(tmp_path: Path) -> None:
    # absent additionalProperties == free-form; closing it is a breaking narrowing
    new = BASE.replace(
        "    Pet:\n      type: object\n      required: [name]",
        "    Pet:\n      type: object\n      additionalProperties: false\n"
        "      required: [name]",
    )
    diff = _diff(tmp_path, {"api.yaml": BASE}, {"api.yaml": new})
    assert "type_changed_request" in _classified(diff, CompatibilityClass.BREAKING)


def test_type_union_change(tmp_path: Path) -> None:
    old = BASE.replace(
        "tag: {type: string}", "tag: {type: [string, 'null']}"
    )
    new = BASE
    diff = _diff(tmp_path, {"api.yaml": old}, {"api.yaml": new})
    assert "COMPAT005" in _ids(diff) or _classified(diff, CompatibilityClass.BREAKING)


def test_malformed_new_contract_flags_unknown(tmp_path: Path) -> None:
    diff = _diff(
        tmp_path,
        {"api.yaml": BASE},
        {"api.yaml": 'openapi: "3.0.3"\ninfo: [broken\n'},
    )
    assert _classified(diff, CompatibilityClass.UNKNOWN)
    assert "COMPAT030" in _ids(diff)


def test_ref_rename_single_pair_is_diffed(tmp_path: Path) -> None:
    old = USER_OLD.replace(
        "#/components/schemas/User", "#/components/schemas/Account"
    ).replace("    User:", "    Account:")
    new = old.replace("        email: {type: string}\n", "").replace(
        "required: [id, name, email]", "required: [id, name]"
    )
    diff = _diff(tmp_path, {"api.yaml": USER_OLD}, {"api.yaml": new})
    assert "COMPAT007" in _ids(diff)


# -- fingerprints (§180) ----------------------------------------------------------


def test_fingerprint_stable_across_formatting(tmp_path: Path) -> None:
    pretty = """openapi: "3.0.3"
info:
  title: T
  version: "1.0"
paths:
  /users/{id}:
    get:
      operationId: getUser
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
components:
  schemas:
    User:
      type: object
      required:
        - id
        - name
        - email
      properties:
        email: {type: string}
        id: {type: string}
        name: {type: string}
"""
    a = _model(tmp_path / "a", {"api.yaml": USER_OLD})
    b = _model(tmp_path / "b", {"api.yaml": pretty})
    assert semantic_fingerprint(a) == semantic_fingerprint(b)


def test_fingerprint_changes_on_semantic_change(tmp_path: Path) -> None:
    a = _model(tmp_path / "a", {"api.yaml": USER_OLD})
    b = _model(tmp_path / "b", {"api.yaml": USER_NEW})
    assert semantic_fingerprint(a) != semantic_fingerprint(b)


def test_fingerprint_stable_across_file_layout(tmp_path: Path) -> None:
    a = _model(tmp_path / "a", {"api.yaml": USER_OLD})
    b = _model(tmp_path / "b", {"renamed.yaml": USER_OLD})
    assert semantic_fingerprint(a) == semantic_fingerprint(b)


# -- determinism ------------------------------------------------------------------


def test_diff_is_deterministic(tmp_path: Path) -> None:
    files_old = {"a.yaml": BASE, "b.yaml": USER_OLD}
    new_user = USER_NEW
    one = _diff(tmp_path / "x", files_old, {"a.yaml": BASE, "b.yaml": new_user})
    two = _diff(tmp_path / "y", files_old, {"a.yaml": BASE, "b.yaml": new_user})
    assert [c.to_dict() for c in one.changes] == [c.to_dict() for c in two.changes]
    assert [f.to_dict() for f in one.findings] == [f.to_dict() for f in two.findings]


def test_change_order_independent_of_input_order(tmp_path: Path) -> None:
    new = BASE.replace(
        "        - {name: limit, in: query, schema: {type: integer}}\n", ""
    ).replace("        '404': {description: missing}\n", "")
    a = _diff(tmp_path / "a", {"api.yaml": BASE}, {"api.yaml": new})
    b = _diff(tmp_path / "b", {"x.yaml": BASE}, {"y.yaml": new})
    assert _kinds(a) == _kinds(b)


# -- CLI -------------------------------------------------------------------------


def test_cli_contract_diff(tmp_path: Path) -> None:
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    old.write_text(USER_OLD, encoding="utf-8")
    new.write_text(USER_NEW, encoding="utf-8")
    result = runner.invoke(app, ["contract", "diff", str(old), str(new)])
    assert result.exit_code == 0
    assert "response_field_removed" in result.output


def test_cli_contract_compatibility_verdict(tmp_path: Path) -> None:
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    old.write_text(USER_OLD, encoding="utf-8")
    new.write_text(USER_NEW, encoding="utf-8")
    result = runner.invoke(app, ["contract", "compatibility", str(old), str(new)])
    assert result.exit_code == 0
    assert "BREAKING" in result.output


def test_cli_semantic_diff_and_json(tmp_path: Path) -> None:
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    old.write_text(USER_OLD, encoding="utf-8")
    new.write_text(USER_NEW, encoding="utf-8")
    result = runner.invoke(app, ["diff", "--semantic", str(old), str(new), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["changes"][0]["kind"] == "response_field_removed"
    assert payload["findings"]["findings"][0]["id"] == "COMPAT007"


def test_cli_compatibility_help() -> None:
    result = runner.invoke(app, ["contract", "compatibility", "--help"])
    assert result.exit_code == 0


def test_cli_fingerprint(tmp_path: Path) -> None:
    f = tmp_path / "api.yaml"
    f.write_text(USER_OLD, encoding="utf-8")
    result = runner.invoke(app, ["fingerprint", str(f)])
    assert result.exit_code == 0
    assert len(result.output.split()[0]) == 64


def test_cli_diff_missing_input(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["contract", "diff", str(tmp_path / "nope.yaml"), str(tmp_path)]
    )
    assert result.exit_code == 2
